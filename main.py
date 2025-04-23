import sys
import os
import logging
import vlc
import random  # Add random module
from collections import OrderedDict

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QWidget,
                             QListWidget, QListWidgetItem, QLabel, QStackedWidget, 
                             QFrame, QFileDialog)
from PyQt5.QtCore import Qt, QTimer, QSize, QPoint
from PyQt5.QtGui import QPalette, QColor

class VideoViewer(QMainWindow):
    def __init__(self, video_folder):
        super().__init__()

        # Remove window frame and make it frameless
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        
        # Enable custom window drag
        self._drag_pos = None

        self.video_folder = video_folder
        self.original_files = []  # Store original order
        self.video_files = []
        self.current_video_index = 0

        self.setWindowTitle("TikTok-like Video Viewer")
        self.setGeometry(100, 100, 720, 1280) # Set a typical phone-like aspect ratio

        # Add minimum/maximum sizes
        self.setMinimumSize(400, 600)
        self.setMaximumSize(1920, 1080)

        # Set dark theme for title bar and window
        self.setStyleSheet("""
            QMainWindow {
                background-color: #000000;
                border: none;
            }
            QFrame {
                background-color: #000000;
                border: none;
            }
        """)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        self.layout = QVBoxLayout()
        self.central_widget.setLayout(self.layout)

        # Replace stacked widget with single frame for VLC
        self.video_frame = QFrame()
        self.video_frame.setAutoFillBackground(True)
        self.layout.addWidget(self.video_frame)

        # Add timer for handling video end events
        self.end_timer = QTimer()
        self.end_timer.setSingleShot(True)
        self.end_timer.timeout.connect(self.handle_video_end)
        
        # Initialize VLC with minimal options
        vlc_options = [
            '--quiet',              # Suppress most messages
            '--verbose=0',          # Reduce verbosity
            '--no-plugins-cache',   # Don't use plugins cache
            '--no-stats',          # Don't log statistics
            '--no-sub-autodetect-file'  # Don't look for subtitles
        ]
        self.instance = vlc.Instance(vlc_options)
        if not self.instance:
            logger.error("Failed to create VLC instance")
            sys.exit(1)
            
        self.media_player = self.instance.media_player_new()
        if not self.media_player:
            logger.error("Failed to create media player")
            sys.exit(1)

        # Configure VLC player options
        self.media_player.set_hwnd(self.video_frame.winId())
        
        # Media options for individual files
        self.vlc_media_options = [
            'avcodec-hw=none',
            'avcodec-threads=1',
            'avcodec-fast',
            'skip-frames=0',
            'vout=direct3d11'
        ]

        # Set up event manager for end of media detection
        self.event_manager = self.media_player.event_manager()
        self.event_manager.event_attach(vlc.EventType.MediaPlayerEndReached, self.on_media_end)

        # Add video cache
        self.cache_size = 7  # Current + 3 before + 3 after
        self.media_cache = OrderedDict()

        self.load_videos()
        self.play_current_video()

    def load_videos(self):
        """Scans the specified folder for video files."""
        if not os.path.isdir(self.video_folder):
            print(f"Error: Folder not found at {self.video_folder}")
            return

        # Supported video extensions (you can add more)
        valid_extensions = ('.mp4', '.mov', '.avi', '.mkv', '.wmv')

        for entry in os.listdir(self.video_folder):
            full_path = os.path.join(self.video_folder, entry)
            if os.path.isfile(full_path) and entry.lower().endswith(valid_extensions):
                self.original_files.append(full_path)

        # Create shuffled playlist
        self.video_files = self.original_files.copy()
        random.shuffle(self.video_files)

        if not self.video_files:
            print(f"No supported video files found in {self.video_folder}")
            # Add a placeholder message if no videos are found
            no_videos_label = QLabel("No videos found in the specified folder.")
            no_videos_label.setAlignment(Qt.AlignCenter)
            no_videos_label.setStyleSheet("color: white; font-size: 20px;")
            self.layout.addWidget(no_videos_label)

    def preload_videos(self):
        """Preloads videos within the sliding window."""
        if not self.video_files:
            return

        start_idx = max(0, self.current_video_index - 3)
        end_idx = min(len(self.video_files), self.current_video_index + 4)
        
        # Remove videos outside the window
        cached_indices = list(self.media_cache.keys())
        for idx in cached_indices:
            if idx < start_idx or idx >= end_idx:
                self.media_cache.pop(idx).release()

        # Load videos within the window
        for idx in range(start_idx, end_idx):
            if idx not in self.media_cache:
                video_path = self.video_files[idx]
                media = self.instance.media_new(video_path)
                for option in self.vlc_media_options:
                    media.add_option(option)
                media.parse()  # Pre-parse the media
                self.media_cache[idx] = media

    def adjust_window_size(self, media):
        """Adjusts window size based on video dimensions."""
        # Wait a bit for media to be parsed
        media.parse()
        
        # Get video dimensions from media player
        video_width = self.media_player.video_get_width()
        video_height = self.media_player.video_get_height()
        
        if video_width == 0 or video_height == 0:
            # Fallback sizes if we can't get dimensions
            video_width = 720
            video_height = 1280
            
        # Calculate target size maintaining aspect ratio
        screen = QApplication.primaryScreen().geometry()
        max_height = int(screen.height() * 0.9)  # 90% of screen height
        
        # Calculate new dimensions
        aspect_ratio = video_width / video_height
        target_height = min(max_height, video_height)
        target_width = int(target_height * aspect_ratio)
        
        # Set new size with some padding
        padding = 40
        new_width = min(target_width + padding, screen.width())
        new_height = min(target_height + padding, screen.height())
        self.resize(new_width, new_height)
        
        # Center window
        self.center_window()
        
    def center_window(self):
        """Centers the window on the screen."""
        frame_geo = self.frameGeometry()
        screen_center = QApplication.primaryScreen().geometry().center()
        frame_geo.moveCenter(screen_center)
        self.move(frame_geo.topLeft())

    def play_current_video(self):
        """Loads and plays the video at the current index."""
        if 0 <= self.current_video_index < len(self.video_files):
            # Ensure current video is in cache
            if self.current_video_index not in self.media_cache:
                video_path = self.video_files[self.current_video_index]
                media = self.instance.media_new(video_path)
                for option in self.vlc_media_options:
                    media.add_option(option)
                media.parse()
                self.media_cache[self.current_video_index] = media

            media = self.media_cache[self.current_video_index]
            if media.get_duration() == -1:
                logger.error(f"Failed to load video: {self.video_files[self.current_video_index]}")
                self.scroll_down()
                return

            self.media_player.set_media(media)
            self.media_player.play()
            
            # Wait a short moment for video to start before adjusting size
            QTimer.singleShot(100, lambda: self.adjust_window_size(media))
            
            logger.info(f"Attempting to play: {self.video_files[self.current_video_index]}")
            
            # Preload adjacent videos
            self.preload_videos()

    def toggle_play_pause(self):
        """Toggles play/pause state of the current video."""
        if self.media_player.is_playing():
            self.media_player.pause()
        else:
            self.media_player.play()

    def scroll_down(self):
        """Scrolls to the next video."""
        if self.current_video_index < len(self.video_files) - 1:
            self.media_player.stop()
            self.current_video_index += 1
            self.play_current_video()

    def scroll_up(self):
        """Scrolls to the previous video."""
        if self.current_video_index > 0:
            self.media_player.stop()
            self.current_video_index -= 1
            self.play_current_video()

    def mousePressEvent(self, event):
        """Handle mouse press for window dragging."""
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.pos()
            event.accept()

    def mouseMoveEvent(self, event):
        """Handle window dragging."""
        if self._drag_pos is not None:
            self.move(event.globalPos() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        """Handle mouse release for window dragging."""
        if event.button() == Qt.LeftButton:
            self._drag_pos = None
            event.accept()

    def keyPressEvent(self, event):
        """Handles key press events for scrolling."""
        if event.key() == Qt.Key_Escape:  # Add escape key to close
            self.close()
        elif event.key() == Qt.Key_Down:
            self.scroll_down()
        elif event.key() == Qt.Key_Up:
            self.scroll_up()
        elif event.key() == Qt.Key_Space:
            self.toggle_play_pause()
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event):
        """Handles mouse wheel events for scrolling."""
        if event.angleDelta().y() < 0: # Scroll down
            self.scroll_down()
        elif event.angleDelta().y() > 0: # Scroll up
            self.scroll_up()

    def on_media_end(self, event):
        """Handler for when a video finishes playing - called from VLC thread."""
        self.end_timer.start(50)  # Schedule the actual handling in the main thread

    def handle_video_end(self):
        """Handles video end in the main thread."""
        if self.current_video_index < len(self.video_files) - 1:
            self.scroll_down()
        else:
            self.current_video_index = 0
            self.play_current_video()

    def closeEvent(self, event):
        """Clean up VLC resources when closing."""
        self.media_player.stop()
        # Clear the cache
        for media in self.media_cache.values():
            media.release()
        self.media_cache.clear()
        self.media_player.release()
        self.instance.release()
        super().closeEvent(event)


def get_cache_file_path():
    """Returns the path to the cache file."""
    return os.path.join(os.path.dirname(__file__), 'last_folder.txt')

def save_folder_to_cache(folder_path):
    """Saves the folder path to cache file."""
    try:
        with open(get_cache_file_path(), 'w') as f:
            f.write(folder_path)
    except Exception as e:
        logger.error(f"Failed to save cache: {e}")

def get_cached_folder():
    """Returns the cached folder path if it exists and is valid."""
    try:
        cache_file = get_cache_file_path()
        if os.path.exists(cache_file):
            with open(cache_file, 'r') as f:
                folder = f.read().strip()
                if os.path.isdir(folder):
                    return folder
    except Exception as e:
        logger.error(f"Failed to read cache: {e}")
    return os.path.expanduser("~")  # Default to home directory


if __name__ == '__main__':
    app = QApplication(sys.argv)

    # Try to get and use cached folder
    video_folder_path = get_cached_folder()
    
    # If no valid cached folder, show dialog
    if not os.path.isdir(video_folder_path):
        video_folder_path = QFileDialog.getExistingDirectory(
            None,
            "Select Folder Containing Videos",
            os.path.expanduser("~"),
            QFileDialog.ShowDirsOnly
        )
        
        if not video_folder_path:  # User cancelled the dialog
            print("No folder selected. Exiting...")
            sys.exit(0)

        # Save the new selection to cache
        save_folder_to_cache(video_folder_path)
    
    logger.info(f"Using video folder: {video_folder_path}")
    viewer = VideoViewer(video_folder_path)
    viewer.show()
    sys.exit(app.exec_())
