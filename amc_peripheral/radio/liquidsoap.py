import socket
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger('liquidsoap_controller')

class LiquidsoapController:
    """
    A Python controller for interacting with Liquidsoap via telnet.
    
    This class allows you to send commands to a running Liquidsoap instance
    through its telnet interface, enabling dynamic control of the radio stream.
    """
    
    def __init__(self, host: str = 'localhost', port: int = 1234, timeout: int = 3):
        """
        Initialize the Liquidsoap controller.
        
        Args:
            host: Hostname or IP address of the Liquidsoap server
            port: Port number of the telnet interface
            timeout: Socket timeout in seconds
        """
        self.host = host
        self.port = port
        self.timeout = timeout
    
    def _send_command(self, command: str) -> str:
        """
        Send a command to Liquidsoap and return the response.
        
        Args:
            command: The command to send to Liquidsoap
            
        Returns:
            The response from Liquidsoap as a string
            
        Raises:
            ConnectionError: If unable to connect to Liquidsoap
            TimeoutError: If the command times out
        """
        sock = None
        try:
            # Create a socket and connect to the Liquidsoap telnet interface
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((self.host, self.port))
            
            # Send the command with a newline
            cmd_bytes = (command + '\n').encode('utf-8')
            sock.sendall(cmd_bytes)
            
            # Read the response
            response = b''
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk
                # Check if the response is complete (END marker)
                break
                if response.endswith(b'END\n'):
                    break
            
            # Convert response to string and clean it up
            response_str = response.decode('utf-8').strip()
            # Remove the END marker
            if response_str.endswith('END'):
                response_str = response_str[:-3].strip()
                
            return response_str
            
        except socket.timeout:
            error_msg = f"Timeout when sending command '{command}' to Liquidsoap"
            logger.error(error_msg)
            raise TimeoutError(error_msg)
            
        except ConnectionRefusedError:
            error_msg = f"Connection refused: Make sure Liquidsoap is running and telnet is enabled on {self.host}:{self.port}"
            logger.error(error_msg)
            raise ConnectionError(error_msg)
            
        except Exception as e:
            error_msg = f"Error communicating with Liquidsoap: {e}"
            logger.error(error_msg)
            raise
            
        finally:
            # Always close the socket
            if sock:
                sock.close()
    
    def push_to_queue(self, queue_name: str, uri: str) -> bool:
        """
        Push a URI to a Liquidsoap queue.
        
        Args:
            queue_name: The name of the queue (e.g., 'requests')
            uri: The URI to push (e.g., '/path/to/file.mp3')
            
        Returns:
            True if the push was successful, False otherwise
        """
        command = f"{queue_name}.push {uri}"
        try:
            response = self._send_command(command)
            success = response.lower() == 'true'
            if success:
                logger.info(f"Successfully pushed {uri} to {queue_name}")
            else:
                logger.warning(f"Failed to push {uri} to {queue_name}: {response}")
            return success
        except Exception as e:
            logger.error(f"Error pushing to queue {queue_name}: {e}")
            return False
    
    def get_queue_length(self, queue_name: str) -> Optional[int]:
        """
        Get the current length of a queue.
        
        Args:
            queue_name: The name of the queue
            
        Returns:
            The number of items in the queue, or None if an error occurred
        """
        command = f"{queue_name}.length"
        try:
            response = self._send_command(command)
            return int(response)
        except (ValueError, Exception) as e:
            logger.error(f"Error getting queue length for {queue_name}: {e}")
            return None
    
    def skip_current_track(self, source_name: str = 'radio') -> bool:
        """
        Skip the current track.
        
        Args:
            source_name: The name of the source to skip
            
        Returns:
            True if successful, False otherwise
        """
        command = f"{source_name}.skip"
        try:
            response = self._send_command(command)
            success = response.lower() == 'true'
            if success:
                logger.info(f"Successfully skipped current track on {source_name}")
            else:
                logger.warning(f"Failed to skip track on {source_name}: {response}")
            return success
        except Exception as e:
            logger.error(f"Error skipping track on {source_name}: {e}")
            return False
    
    def get_current_metadata(self, source_name: str = 'radio') -> Optional[Dict[str, str]]:
        """
        Get metadata about the currently playing track.
        
        Args:
            source_name: The name of the source
            
        Returns:
            A dictionary of metadata, or None if an error occurred
        """
        command = f"{source_name}.metadata"
        try:
            response = self._send_command(command)
            # Parse the metadata response
            metadata = {}
            for line in response.split('\n'):
                if '=' in line:
                    key, value = line.split('=', 1)
                    metadata[key.strip()] = value.strip()
            return metadata
        except Exception as e:
            logger.error(f"Error getting metadata for {source_name}: {e}")
            return None
    
    def get_remaining_time(self, source_name: str = 'radio') -> Optional[float]:
        """
        Get the remaining time of the current track in seconds.
        
        Args:
            source_name: The name of the source
            
        Returns:
            The remaining time in seconds, or None if an error occurred
        """
        command = f"{source_name}.remaining"
        try:
            response = self._send_command(command)
            return float(response)
        except (ValueError, Exception) as e:
            logger.error(f"Error getting remaining time for {source_name}: {e}")
            return None
    
    def get_uptime(self) -> Optional[float]:
        """
        Get Liquidsoap's uptime in seconds.
        
        Returns:
            The uptime in seconds, or None if an error occurred
        """
        command = "uptime"
        try:
            response = self._send_command(command)
            return float(response)
        except (ValueError, Exception) as e:
            logger.error(f"Error getting uptime: {e}")
            return None
    
    def reload_playlist(self, playlist_name: str) -> bool:
        """
        Reload a playlist.
        
        Args:
            playlist_name: The name of the playlist to reload
            
        Returns:
            True if successful, False otherwise
        """
        command = f"{playlist_name}.reload"
        try:
            response = self._send_command(command)
            success = "reloaded" in response.lower()
            if success:
                logger.info(f"Successfully reloaded {playlist_name}")
            else:
                logger.warning(f"Failed to reload {playlist_name}: {response}")
            return success
        except Exception as e:
            logger.error(f"Error reloading {playlist_name}: {e}")
            return False
    
    def get_status(self) -> Optional[Dict[str, Any]]:
        """
        Get the general status of Liquidsoap.
        
        Returns:
            A dictionary with status information, or None if an error occurred
        """
        status = {}
        
        try:
            # Get uptime
            uptime = self.get_uptime()
            if uptime is not None:
                status['uptime'] = uptime
                
            # Get current metadata
            metadata = self.get_current_metadata()
            if metadata:
                status['current_track'] = metadata
                
            # Get remaining time
            remaining = self.get_remaining_time()
            if remaining is not None:
                status['remaining_time'] = remaining
                
            return status
        except Exception as e:
            logger.error(f"Error getting Liquidsoap status: {e}")
            return None


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Create the controller
    ls = LiquidsoapController(host='localhost', port=1234)
    
    try:
        # Example: Push a song to the requests queue
        success = ls.push_to_queue('requests', '/path/to/song.mp3')
        logger.info(f"Push song result: {success}")
        
        # Example: Get current playing track info
        metadata = ls.get_current_metadata()
        logger.info(f"Current track: {metadata}")
        
        # Example: Skip the current track
        ls.skip_current_track()
        
        # Example: Get overall status
        status = ls.get_status()
        logger.info(f"Liquidsoap status: {status}")
        
    except ConnectionError as e:
        logger.error(f"Connection error: {e}")
    except Exception as e:
        logger.error(f"Error: {e}")
