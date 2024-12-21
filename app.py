from flask import Flask, request, jsonify, send_file, render_template
import yt_dlp
import os
import time
from werkzeug.wsgi import FileWrapper
import threading

app = Flask(__name__)

# Create a temporary folder for downloads
TEMP_FOLDER = "temp_downloads"
if not os.path.exists(TEMP_FOLDER):
    os.makedirs(TEMP_FOLDER)

# Track downloaded files and their status
downloaded_files = {}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get-formats', methods=['POST'])
def get_formats():
    try:
        video_url = request.json['url']
        
        # Configure yt-dlp options for format extraction
        ydl_opts = {
            'quiet': True,
            'no_warnings': True
        }
        
        # Extract video information and available formats
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            
            formats = []
            # Add MP3 option first
            formats.append({
                'format_id': 'bestaudio',
                'ext': 'mp3',
                'type': 'audio',
                'quality': '192',
                'filesize': 'N/A',
                'display': 'Audio: MP3 (192kbps)'
            })
            
            for fmt in info.get('formats', []):
                if fmt.get('ext'):
                    size = fmt.get('filesize') or fmt.get('filesize_approx') or 0
                    size_mb = size / (1024 * 1024)
                    
                    format_info = {
                        'format_id': fmt['format_id'],
                        'ext': fmt['ext'],
                        'filesize': f"{size_mb:.1f} MB",
                        'format_note': fmt.get('format_note', ''),
                    }
                    
                    if fmt.get('height'):  # Video formats
                        format_info['type'] = 'video'
                        format_info['quality'] = f"{fmt['height']}p"
                        format_info['display'] = f"Video: {fmt['height']}p {fmt['ext']} ({size_mb:.1f} MB)"
                        formats.append(format_info)
            
            # Sort formats by quality (height for video)
            formats.sort(key=lambda x: int(x.get('quality', '0').replace('p', '')) if x['type'] == 'video' else 0, 
                        reverse=True)
            
            return jsonify({
                'success': True,
                'title': info.get('title', 'Unknown'),
                'duration': info.get('duration', 0),
                'formats': formats
            })
            
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        })

@app.route('/download', methods=['POST'])
def download():
    try:
        video_url = request.json['url']
        format_id = request.json.get('format_id', 'best')
        download_type = request.json.get('type', 'video')  # New parameter to specify download type
        
        # Create a unique filename using timestamp
        timestamp = int(time.time())
        
        # Set filename extension based on download type
        extension = 'mp3' if download_type == 'audio' else 'mp4'
        filename = f'download_{timestamp}.{extension}'
        output_path = os.path.join(TEMP_FOLDER, filename)
        
        # Configure yt-dlp options based on download type
        if download_type == 'audio':
            ydl_opts = {
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'outtmpl': output_path[:-4],  # Remove .mp3 extension as it will be added by postprocessor
                'quiet': True
            }
        else:
            ydl_opts = {
                'format': f"{format_id}+bestaudio/best" if format_id != 'bestaudio' else 'bestaudio',
                'merge_output_format': 'mp4',
                'outtmpl': output_path,
                'quiet': True
            }
        
        # Download the video/audio
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            title = info['title']
        
        # For audio downloads, adjust the file path to include .mp3 extension
        if download_type == 'audio':
            output_path = f"{output_path[:-4]}.mp3"
        
        # Add file to tracking dictionary
        downloaded_files[filename] = {
            'path': output_path,
            'downloaded': False,
            'timestamp': time.time()
        }
        
        return jsonify({
            'success': True,
            'message': f"{'Audio' if download_type == 'audio' else 'Video'} downloaded successfully",
            'filename': filename,
            'title': title
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        })

@app.route('/get-video/<filename>')
def get_video(filename):
    try:
        if filename not in downloaded_files:
            return "File not found", 404
        
        file_path = downloaded_files[filename]['path']
        if not os.path.exists(file_path):
            return "File not found", 404

        def cleanup():
            try:
                # Wait a short moment to ensure the download has started
                time.sleep(1)
                if os.path.exists(file_path):
                    os.remove(file_path)
                del downloaded_files[filename]
            except Exception as e:
                print(f"Cleanup error: {str(e)}")

        # Start cleanup thread after sending file
        cleanup_thread = threading.Thread(target=cleanup)
        cleanup_thread.start()

        return send_file(
            file_path,
            as_attachment=True,
            download_name=filename
        )

    except Exception as e:
        return str(e), 500

# Cleanup function for old undownloaded files
def cleanup_old_files():
    current_time = time.time()
    files_to_delete = []
    
    for filename, info in downloaded_files.items():
        # Delete files older than 1 hour or already downloaded
        if current_time - info['timestamp'] > 3600 or info['downloaded']:
            file_path = info['path']
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception as e:
                    print(f"Error deleting file {filename}: {str(e)}")
            files_to_delete.append(filename)
    
    # Remove entries from tracking dictionary
    for filename in files_to_delete:
        downloaded_files.pop(filename, None)

# Schedule periodic cleanup
def run_periodic_cleanup():
    while True:
        cleanup_old_files()
        time.sleep(3600)  # Run every hour

if __name__ == '__main__':
    # Start cleanup thread
    cleanup_thread = threading.Thread(target=run_periodic_cleanup, daemon=True)
    cleanup_thread.start()
    
    app.run(debug=True)