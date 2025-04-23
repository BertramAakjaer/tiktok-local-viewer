#!/usr/bin/env python3
"""
TikTok-style Local Video Viewer
------------------------------
A standalone application that provides a TikTok-like interface for viewing local video files.
Features:
- Frameless window with custom drag functionality
- Video playback using VLC backend
- Vertical scrolling navigation
- Smart video preloading
- Window size adaptation based on video dimensions
- Last folder memory

Dependencies:
- PyQt5: For the GUI framework
- python-vlc: For video playback functionality
- VLC media player: Must be installed on the system
"""

import sys
import os
import logging
import vlc
import random
import subprocess
import ctypes
from ctypes.wintypes import MAX_PATH
from collections import OrderedDict

# Configure logging for debugging and error tracking
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QWidget,
                             QListWidget, QListWidgetItem, QLabel, QStackedWidget, 
                             QFrame, QFileDialog)
from PyQt5.QtCore import Qt, QTimer, QSize, QPoint, pyqtSignal
from PyQt5.QtGui import QPalette, QColor

class VideoViewer(QMainWindow):
    """
    Main application window class that handles video playback and user interaction.
    
    This class creates a frameless window that mimics TikTok's interface for viewing
    local video files. It handles video playback, window positioning, and user input.
    
    Attributes:
        video_folder (str): Path to the folder containing video files
        original_files (list): List of video files in their original order
        video_files (list): Shuffled list of video files for playback
        current_video_index (int): Index of the currently playing video
        cache_size (int): Number of videos to keep in memory cache (current + 3 before + 3 after)
        media_cache (OrderedDict): Cache storing preloaded video media objects
        _drag_pos (QPoint): Tracks mouse position during window dragging
        _last_position (QPoint): Stores the last window position
    """
    
    # Add signal for video end event
    video_ended_signal = pyqtSignal()
    
    def __init__(self, video_folder):
        """
        Initialize the video viewer application.
        
        Args:
            video_folder (str): Path to the folder containing video files
        """
        super().__init__()

        # Configure window properties for a frameless, always-on-top display
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        
        # Initialize window dragging variables
        self._drag_pos = None
        self._last_position = None

        self.video_folder = video_folder
        self.original_files = []  # Preserve original file order
        self.video_files = []     # Will contain shuffled playlist
        self.current_video_index = 0

        # Set up the main window properties
        self.setWindowTitle("TikTok-like Video Viewer")
        self.setGeometry(100, 100, 720, 1280)  # Mobile-like aspect ratio
        self.setMinimumSize(400, 600)          # Prevent window from being too small
        self.setMaximumSize(1920, 1080)        # Prevent window from being too large

        # Apply dark theme styling
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

        # Set up the central widget and layout
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout()
        self.central_widget.setLayout(self.layout)

        # Create video frame
        self.video_frame = QFrame()
        self.video_frame.setAutoFillBackground(True)
        self.layout.addWidget(self.video_frame)

        # Initialize video end detection timer
        self.end_timer = QTimer()
        self.end_timer.setSingleShot(True)
        self.end_timer.timeout.connect(self.handle_video_end)
        
        # Initialize VLC instance with optimized settings
        vlc_options = [
            '--quiet',              # Minimize VLC messages
            '--verbose=0',          # Reduce logging verbosity
            '--no-plugins-cache',   # Disable plugins cache
            '--no-stats',          # Disable statistics logging
            '--no-sub-autodetect-file',  # Disable subtitle auto-detection
            '--input-repeat=65535'  # Set repeat count to a high number
        ]
        self.instance = vlc.Instance(vlc_options)
        if not self.instance:
            logger.error("Failed to create VLC instance")
            sys.exit(1)
            
        # Create and configure media player
        self.media_player = self.instance.media_player_new()
        if not self.media_player:
            logger.error("Failed to create media player")
            sys.exit(1)

        # Attach media player to our video frame
        self.media_player.set_hwnd(self.video_frame.winId())
        
        # Configure VLC media options for optimal playback
        self.vlc_media_options = [
            'avcodec-hw=none',          # Disable hardware acceleration
            'avcodec-threads=1',        # Single threaded decoding
            'avcodec-fast',             # Enable fast decoding
            'skip-frames=0',            # Don't skip frames
            'vout=direct3d11',          # Use Direct3D11 video output
            '--loop',                   # Enable looping
            '--repeat'                  # Enable repeat mode
        ]

        # Connect video end signal to handler
        self.video_ended_signal.connect(self.handle_video_end)
        
        # Set up VLC event manager for end-of-media detection
        self.event_manager = self.media_player.event_manager()
        self.event_manager.event_attach(vlc.EventType.MediaPlayerEndReached, self.on_media_end)

        # Initialize video cache
        self.cache_size = 7  # Cache window size (current + 3 before + 3 after)
        self.media_cache = OrderedDict()

        # Load videos and start playback
        self.load_videos()
        self.play_current_video()

    def load_videos(self):
        """
        Scan the video folder for supported video files and create a shuffled playlist.
        If the folder is invalid or contains no videos, shows a folder selection dialog.
        """
        while not os.path.isdir(self.video_folder) or not self.has_video_files(self.video_folder):
            print(f"No valid videos found in: {self.video_folder}")
            new_folder = QFileDialog.getExistingDirectory(
                self,
                "Select Folder Containing Videos",
                os.path.expanduser("~"),
                QFileDialog.ShowDirsOnly
            )
            
            if not new_folder:  # User canceled selection
                print("No folder selected. Exiting...")
                sys.exit(0)
                
            self.video_folder = new_folder
            save_folder_to_cache(new_folder)  # Save the new folder choice

        # Clear any existing files
        self.original_files.clear()
        self.video_files.clear()

        # Supported video extensions
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
            
    def has_video_files(self, folder):
        """
        Check if a folder contains any supported video files.
        
        Args:
            folder (str): Path to check for video files
            
        Returns:
            bool: True if folder contains supported video files, False otherwise
        """
        valid_extensions = ('.mp4', '.mov', '.avi', '.mkv', '.wmv')
        for entry in os.listdir(folder):
            if entry.lower().endswith(valid_extensions):
                return True
        return False

    def preload_videos(self):
        """
        Manage the video preload cache within a sliding window around the current video.
        
        Maintains a cache of parsed media objects for smooth playback:
        - Removes videos that fall outside the cache window
        - Loads upcoming videos within the window
        - Window size is determined by self.cache_size
        """
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
        """
        Adjust the window size to match video dimensions while maintaining aspect ratio.
        
        Args:
            media (vlc.Media): VLC media object containing video metadata
            
        The window size is calculated to:
        - Maintain aspect ratio
        - Be at least half the screen height
        - Not exceed 90% of screen height
        - Include padding for controls
        - Preserve window position after first placement
        """
        # Store current position before resizing
        current_pos = self.pos()
        
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
        min_height = int(screen.height() * 0.5)  # 50% of screen height
        max_height = int(screen.height() * 0.9)  # 90% of screen height
        
        # Calculate new dimensions, ensuring minimum height
        aspect_ratio = video_width / video_height
        target_height = max(min_height, min(max_height, video_height))
        target_width = int(target_height * aspect_ratio)
        
        # Set new size with some padding
        padding = 40
        new_width = min(target_width + padding, screen.width())
        new_height = min(target_height + padding, screen.height())
        
        # If this is the first video, center the window
        if self._last_position is None:
            self.resize(new_width, new_height)
            self.center_window()
            self._last_position = self.pos()
        else:
            # Otherwise maintain the current position
            self.resize(new_width, new_height)
            self.move(current_pos)

    def center_window(self):
        """
        Center the window on the primary screen.
        
        This is only called once when the application first starts.
        Subsequent video loads will maintain the window's position.
        """
        frame_geo = self.frameGeometry()
        screen_center = QApplication.primaryScreen().geometry().center()
        frame_geo.moveCenter(screen_center)
        self.move(frame_geo.topLeft())

    def play_current_video(self):
        """
        Load and play the video at the current index.
        """
        if 0 <= self.current_video_index < len(self.video_files):
            # Ensure current video is in cache
            if self.current_video_index not in self.media_cache:
                video_path = self.video_files[self.current_video_index]
                media = self.instance.media_new(video_path)
                
                # Set media options for looping
                media.add_option(':input-repeat=65535')  # Set a high repeat count
                media.add_option(':repeat=65535')        # Enable repeat mode
                
                media.parse()
                self.media_cache[self.current_video_index] = media

            media = self.media_cache[self.current_video_index]
            if media.get_duration() == -1:
                logger.error(f"Failed to load video: {self.video_files[self.current_video_index]}")
                self.scroll_down()
                return

            self.media_player.set_media(media)
            
            # Set looping at the player level as well
            self.media_player.set_media(media)
            self.media_player.play()
            
            # Create a timer to check video position periodically
            self.position_timer = QTimer()
            self.position_timer.setInterval(500)  # Check every 500ms
            self.position_timer.timeout.connect(self.check_video_position)
            self.position_timer.start()
            
            # Wait a short moment for video to start before adjusting size
            QTimer.singleShot(100, lambda: self.adjust_window_size(media))
            
            logger.info(f"Playing (looped): {self.video_files[self.current_video_index]}")
            
            # Preload adjacent videos
            self.preload_videos()

    def check_video_position(self):
        """Check if video has ended and restart if necessary."""
        if self.media_player.get_state() == vlc.State.Ended:
            self.media_player.set_position(0)
            self.media_player.play()
        elif self.media_player.get_position() >= 0.99:  # If near the end (99%)
            self.media_player.set_position(0)
            self.media_player.play()

    def scroll_down(self):
        """
        Navigate to the next video in the playlist.
        
        - Stops current video
        - Increments video index
        - Starts playback of next video
        """
        if self.current_video_index < len(self.video_files) - 1:
            # Stop the position timer if it exists
            if hasattr(self, 'position_timer'):
                self.position_timer.stop()
            self.media_player.stop()
            self.current_video_index += 1
            self.play_current_video()

    def scroll_up(self):
        """
        Navigate to the previous video in the playlist.
        
        - Stops current video
        - Decrements video index
        - Starts playback of previous video
        """
        if self.current_video_index > 0:
            # Stop the position timer if it exists
            if hasattr(self, 'position_timer'):
                self.position_timer.stop()
            self.media_player.stop()
            self.current_video_index -= 1
            self.play_current_video()

    def toggle_play_pause(self):
        """
        Toggle between play and pause states for the current video.
        Uses VLC's is_playing() to determine current state and toggle appropriately.
        """
        if self.media_player.is_playing():
            self.media_player.pause()
        else:
            self.media_player.play()

    def show_in_explorer(self):
        """
        Show the current video file in Windows File Explorer.
        Uses a simple command that reliably highlights the file.
        """
        if 0 <= self.current_video_index < len(self.video_files):
            # Get the absolute path and convert any forward slashes to backslashes
            video_path = os.path.abspath(self.video_files[self.current_video_index]).replace('/', '\\')
            if os.path.exists(video_path):
                # Use string literal with Windows-style path
                cmd = rf'explorer /select,"{video_path}"'
                os.system(cmd)

    def mousePressEvent(self, event):
        """
        Handle mouse press events for window dragging.
        
        Args:
            event (QMouseEvent): Mouse event containing position information
        """
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.pos()
            event.accept()

    def mouseMoveEvent(self, event):
        """
        Handle window dragging when mouse is moved.
        
        Args:
            event (QMouseEvent): Mouse event containing position information
        """
        if self._drag_pos is not None:
            self.move(event.globalPos() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        """
        Handle mouse release to end window dragging.
        
        Args:
            event (QMouseEvent): Mouse event containing button information
        """
        if event.button() == Qt.LeftButton:
            self._drag_pos = None
            event.accept()

    def keyPressEvent(self, event):
        """
        Handle keyboard input for navigation and control.
        
        Supported keys:
        - Escape: Close application
        - Down Arrow: Next video
        - Up Arrow: Previous video
        - Space: Toggle play/pause
        - Enter: Show current video in File Explorer
        
        Args:
            event (QKeyEvent): Keyboard event containing key information
        """
        if event.key() == Qt.Key_Escape:
            self.close()
        elif event.key() == Qt.Key_Down:
            self.scroll_down()
        elif event.key() == Qt.Key_Up:
            self.scroll_up()
        elif event.key() == Qt.Key_Space:
            self.toggle_play_pause()
        elif event.key() == Qt.Key_Return:  # Handle Enter key
            self.show_in_explorer()
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event):
        """
        Handle mouse wheel events for video navigation.
        
        Scroll down -> Next video
        Scroll up -> Previous video
        
        Args:
            event (QWheelEvent): Mouse wheel event containing scroll information
        """
        if event.angleDelta().y() < 0: # Scroll down
            self.scroll_down()
        elif event.angleDelta().y() > 0: # Scroll up
            self.scroll_up()

    def on_media_end(self, event):
        """
        Handle video end event from VLC thread.
        Emits a signal to handle the event in the Qt main thread.
        
        Args:
            event (vlc.Event): VLC event object
        """
        # Emit signal to handle in main thread
        self.video_ended_signal.emit()

    def handle_video_end(self):
        """
        Handle video end in the main thread by restarting the same video.
        This method is connected to video_ended_signal and runs in the Qt main thread.
        """
        # Set position to beginning and restart
        self.media_player.set_position(0)
        self.media_player.play()

    def closeEvent(self, event):
        """
        Clean up resources when application closes.
        
        - Stops playback
        - Releases all cached media
        - Releases VLC instance
        
        Args:
            event (QCloseEvent): Close event object
        """
        # Stop the position timer if it exists
        if hasattr(self, 'position_timer'):
            self.position_timer.stop()
        self.media_player.stop()
        # Clear the cache
        for media in self.media_cache.values():
            media.release()
        self.media_cache.clear()
        self.media_player.release()
        self.instance.release()
        super().closeEvent(event)


def get_cache_file_path():
    """
    Get the path to the file storing the last used folder.
    Handles both development and PyInstaller frozen environments.
    
    Returns:
        str: Absolute path to the cache file
    """
    if getattr(sys, 'frozen', False):
        # If the application is run as a bundle (compiled with PyInstaller)
        application_path = os.path.dirname(sys.executable)
    else:
        # If the application is run from a Python interpreter
        application_path = os.path.dirname(os.path.abspath(__file__))
        
    cache_file = os.path.join(application_path, 'last_folder.txt')
    
    # Ensure the directory exists and is writable
    try:
        # Try to create a test file to verify write permissions
        test_file = os.path.join(application_path, 'test_write')
        with open(test_file, 'w') as f:
            f.write('test')
        os.remove(test_file)
        return cache_file
    except (IOError, OSError):
        # If we can't write to the application directory, use the user's documents folder
        documents_path = os.path.expanduser('~/Documents/TikTokViewer')
        os.makedirs(documents_path, exist_ok=True)
        return os.path.join(documents_path, 'last_folder.txt')

def save_folder_to_cache(folder_path):
    """
    Save the current folder path to cache file.
    
    Args:
        folder_path (str): Path to save
        
    Logs any errors that occur during saving.
    """
    try:
        with open(get_cache_file_path(), 'w') as f:
            f.write(folder_path)
    except Exception as e:
        logger.error(f"Failed to save cache: {e}")

def get_cached_folder():
    """
    Retrieve the last used folder path from cache.
    
    Returns:
        str: Path from cache if valid, or user's home directory as fallback
        
    The path is validated to ensure it still exists before being returned.
    """
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
    # Initialize Qt application
    app = QApplication(sys.argv)

    # Get video folder path - either from cache or user selection
    video_folder_path = get_cached_folder()
    
    # If no valid cached folder exists, prompt user for folder selection
    if not os.path.isdir(video_folder_path):
        video_folder_path = QFileDialog.getExistingDirectory(
            None,
            "Select Folder Containing Videos",
            os.path.expanduser("~"),
            QFileDialog.ShowDirsOnly
        )
        
        # Exit if user cancels folder selection
        if not video_folder_path:
            print("No folder selected. Exiting...")
            sys.exit(0)

        # Save selected folder to cache for next time
        save_folder_to_cache(video_folder_path)
    
    # Log selected folder path
    logger.info(f"Using video folder: {video_folder_path}")
    
    # Create and show main application window
    viewer = VideoViewer(video_folder_path)
    viewer.show()
    
    # Start Qt event loop
    sys.exit(app.exec_())
