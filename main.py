import os
import re
import subprocess
from flask import Flask, render_template, redirect, url_for, flash
from flask_wtf import FlaskForm
from wtforms import StringField, IntegerField, BooleanField, SelectField, FieldList, FormField, SubmitField
from wtforms.validators import DataRequired, Optional, Regexp, NumberRange, ValidationError
from flask_bootstrap import Bootstrap5
import traceback
import time

os.chdir(os.path.dirname(os.path.abspath(__file__)))

app = Flask(__name__)
app.config['SECRET_KEY'] = '76345796256943695457634556940864857634596386740010010292576345444444894835766538386735535'
app.config['WTF_CSRF_ENABLED'] = False
Bootstrap5(app)

def validate_file_extension(form, field):
    if not re.match(r'.*\.(mp4|mkv|avi|webm)$', field.data, re.IGNORECASE):
        raise ValidationError('Invalid file format. Only mp4, mkv, avi, and webm are allowed.')

class SegmentForm(FlaskForm):
    start = StringField('Start Time', validators=[Optional(), Regexp(r'^\d{2}:\d{2}:\d{2}$', message="Invalid format.")], render_kw={"placeholder": "00:00:00"})
    end = StringField('End Time', validators=[Optional(), Regexp(r'^\d{2}:\d{2}:\d{2}$', message="Invalid format.")], render_kw={"placeholder": "00:00:00"})

class VideoForm(FlaskForm):
    file_path_input = StringField('Video Input Path', validators=[DataRequired(), validate_file_extension])
    file_path_output = StringField('Video Output Path', default='~/Desktop')
    file_path_output_name = StringField('Output File Name', default='test', description='The output will add `.webm`.')
    segments = FieldList(FormField(SegmentForm), min_entries=1, max_entries=32)
    combine_segments = BooleanField('Splice Segments', default=False)
    video_codec = StringField('Video Codec', default='libvpx-vp9', render_kw={'disabled': True}, description='Only VP9 is supported.')
    file_size = StringField('File Size (K)', default='3900K', description='No further chunk of bytes is written after the limit is exceeded.')
    crf = IntegerField('Constant Rate Factor (CRF)', default=20, validators=[NumberRange(min=0, max=63)], description='0-63 - Lower is better for quality.')
    bitrate = StringField('Bitrate (Kbps)', default='1500K', validators=[Optional(), Regexp(r'^\d{1,4}K$', message="Invalid format.")])
    bitrate_min = StringField('Bitrate, Min (Kbps)', default='100K', validators=[Regexp(r'^\d{1,4}K$', message="Invalid format.")])
    bitrate_max = StringField('Bitrate, Max (Kbps)', default='2000K', validators=[Regexp(r'^\d{1,4}K$', message="Invalid format.")])
    buffer_size = StringField('Rate Control Buffer (Kbps)', default='1000K', validators=[Regexp(r'^\d{1,4}K$', message="Invalid format.")], description='The higher the buffer size, the higher the allowed bitrate variation.')
    framerate = IntegerField('Framerate, Baseline (Hz)', default=30, validators=[NumberRange(min=1, max=200)])
    threads = IntegerField('Threads', default=6, validators=[NumberRange(min=1, max=24)])
    preset_speed = SelectField('Preset Speed', choices=[
        ('ultrafast', 'ultrafast'),
        ('superfast', 'superfast'),
        ('veryfast', 'veryfast'),
        ('faster', 'faster'),
        ('fast', 'fast'),
        ('medium', 'medium'),
        ('slow', 'slow'),
        ('slower', 'slower'),
        ('veryslow', 'veryslow'),
    ], default='medium')
    remove_audio = BooleanField('Remove Audio')
    audio_encoding = StringField('Audio Codec', default='libopus', render_kw={'disabled': True}, description='Only Vorbis is supported.')
    audio_bitrate = StringField('Audio Bitrate, (Kbps)', default='50K', validators=[Optional(), Regexp(r'^\d{1,4}K$', message="Invalid format.")])
    audio_variable_bitrate = BooleanField('Audio Variable Bitrate', default=True)
    submit = SubmitField('Process Video')

@app.route('/', methods=['GET', 'POST'])
def index():
    form = VideoForm()
    if form.validate_on_submit():
        segments = form.segments.data
        
        input_path = os.path.abspath(os.path.expanduser(form.file_path_input.data))
        assert os.path.isfile(input_path), input_path

        output_path = os.path.abspath(os.path.expanduser(form.file_path_output.data))
        assert os.path.isdir(output_path), output_path

        output_name = form.file_path_output_name.data

        commands = []
        for i, segment in enumerate(segments):

            cmd_args = ['ffmpeg', '-y', '-i', input_path]

            segment_output = os.path.join(output_path, f"segment_{time.strftime('%y%d%m%H%M%s')}.webm")
            if segment and segment.get('start') and segment.get('end'):
                start = segment['start']
                end = segment['end']
                segment_output = os.path.join(output_path, f"segment_{time.time()}_ss_{start.replace(':', '_')}_to_{end.replace(':', '_')}.webm")
                cmd_args += ['-ss', start, '-to', end]

            cmd_args += [
                '-c:v', form.video_codec.data,
                '-crf', str(form.crf.data),
                '-b:v', form.bitrate.data, '-minrate', form.bitrate_min.data, '-maxrate', form.bitrate_max.data,
                '-bufsize', form.buffer_size.data,
                '-r', str(form.framerate.data),
                '-threads', str(form.threads.data), '-preset', form.preset_speed.data,
            ]
            
            for cmd_arg in cmd_args:
                assert cmd_arg, cmd_arg

            if form.remove_audio.data:
                cmd_args.append('-an')
            else:
                cmd_args.extend(['-c:a', form.audio_encoding.data, '-b:a', form.audio_bitrate.data])

                if form.audio_variable_bitrate.data:
                    cmd_args.extend(['-vbr', 'on'])
                else:
                    cmd_args.extend(['-vbr', 'off'])

            cmd_args.append(segment_output)
            commands.append((cmd_args, segment_output))

        try:
            for cmd_args, segment_output in commands:
                result = subprocess.run(cmd_args, capture_output=True, text=True)
                if result.returncode != 0:
                    flash(f"Error processing segment: {result.stderr}", "danger")
                    flash(f"COMMAND: {cmd_args}", "danger")
                    return redirect(url_for('index'))

            if form.combine_segments.data and len(commands) > 1:
                segment_files = [segment_output for _, segment_output in commands]
                segment_list_path = os.path.join(output_path, 'segments.txt')
                with open(segment_list_path, 'w') as f:
                    for segment_file in segment_files:
                        f.write(f"file '{segment_file}'\n")

                i = 0
                final_output = os.path.join(output_path, f"{output_name.replace('.webm', '')}_{i}.webm")
                while os.path.isfile(final_output):
                    i += 1
                    final_output = os.path.join(output_path, f"{output_name.replace('.webm', '')}_{i}.webm")

                combine_cmd = [
                    'ffmpeg', '-f', 'concat', '-safe', '0', '-i', segment_list_path,
                    '-c', 'copy',
                    '-crf', str(form.crf.data),
                    '-b:v', form.bitrate.data, '-minrate', form.bitrate_min.data, '-maxrate', form.bitrate_max.data,
                    '-bufsize', form.buffer_size.data,
                    '-r', str(form.framerate.data),
                    '-threads', str(form.threads.data), '-preset', form.preset_speed.data,
                    final_output
                ]
                result = subprocess.run(combine_cmd, capture_output=True, text=True)

                if result.returncode != 0:
                    flash(f"Error combining segments: {result.stderr}", "danger")
                    flash(f"COMMAND: {cmd_args}", "danger")
                else:
                    flash(f"Success! Video saved to {final_output}", "success")
                    flash(f"COMMAND: {cmd_args}", "primary")

        except Exception as e:
            flash(f"An error occurred:\n\n{traceback.format_exception(e)}\n", "danger")

        return redirect(url_for('index'))
    return render_template('main.html', form=form)

if __name__ == '__main__':
    app.run(debug=True)
