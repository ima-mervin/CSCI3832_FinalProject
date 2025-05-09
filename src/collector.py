import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import pandas as pd
import time
import os
import sys
import argparse
import lyricsgenius

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, DEFAULT_OUTPUT_FILE

# Genius API setup
GENIUS_CLIENT_ID = os.getenv("GENIUS_CLIENT_ID")
GENIUS_CLIENT_SECRET = os.getenv("GENIUS_CLIENT_SECRET")
GENIUS_ACCESS_TOKEN = os.getenv("GENIUS_ACCESS_TOKEN")  # Crucial for accessing the Genius API


class SpotifyDataCollector:
    def __init__(self, client_id=None, client_secret=None, genius_token=None):
        """Initialize Spotify and Genius clients with credentials"""
        # Use provided credentials or fall back to config
        self.client_id = client_id or SPOTIFY_CLIENT_ID
        self.client_secret = client_secret or SPOTIFY_CLIENT_SECRET
        self.genius_token = genius_token or GENIUS_ACCESS_TOKEN

        if not self.client_id or not self.client_secret:
            raise ValueError(
                "Missing Spotify API credentials. Set them in .env file or provide as arguments.")

        if not self.genius_token:
            raise ValueError(
                "Missing Genius API token. Set it in .env file.")

        # Set up Spotify client
        client_credentials_manager = SpotifyClientCredentials(
            client_id=self.client_id,
            client_secret=self.client_secret
        )
        self.sp = spotipy.Spotify(
            client_credentials_manager=client_credentials_manager)

        # Set up Genius client
        self.genius = lyricsgenius.Genius(self.genius_token)
        self.genius.verbose = False  # Suppress verbose output
        self.genius.remove_section_headers = True  # Remove section headers (e.g., [Verse])
        self.genius.skip_non_songs = True  # Exclude non-songs


    def get_playlist_tracks(self, playlist_id):
        """Get all tracks from a playlist"""
        results = self.sp.playlist_tracks(playlist_id)
        tracks = results['items']
        while results['next']:
            results = self.sp.next(results)
            tracks.extend(results['items'])
        return tracks

    def get_track_features(self, track_id):
        """Get audio features for a track"""
        try:
            features = self.sp.audio_features(track_id)[0]
            return features
        except Exception as e:
            print(f"Error getting features for {track_id}: {e}")
            return None

    def get_lyrics(self, artist_name, track_name):
        """Fetch lyrics from Genius API"""
        try:
            song = self.genius.search_song(track_name, artist=artist_name)
            if song:
                return song.lyrics
            else:
                return None
        except Exception as e:
            print(f"Error getting lyrics for {track_name} by {artist_name}: {e}")
            return None

    def get_track_data(self, track_item):
        """Extract relevant track data, including lyrics"""
        track = track_item.get('track')
        if not track:  # Skip None tracks
            return None

        try:
            track_id = track.get('id')
            if not track_id:
                return None

            # Basic track info
            artists = track.get('artists', [])
            artist_names = ', '.join([artist.get('name', 'Unknown Artist') for artist in artists if isinstance(artist, dict)])
            artist_ids = ', '.join([artist.get('id', 'Unknown ID') for artist in artists if isinstance(artist, dict) and 'id' in artist])
            
            track_name = track.get('name', 'Unknown Track')
            album = track.get('album', {})
            
            track_data = {
                'id': track_id,
                'name': track_name,
                'popularity': track.get('popularity', 0),
                'explicit': track.get('explicit', False),
                'duration_ms': track.get('duration_ms', 0),
                'album_name': album.get('name', 'Unknown Album') if album else 'Unknown Album',
                'album_release_date': album.get('release_date', 'Unknown Date') if album else 'Unknown Date',
                'artist_names': artist_names,
                'artist_ids': artist_ids
            }

            # Get lyrics
            if artist_names and track_name != 'Unknown Track':
                lyrics = self.get_lyrics(artist_names, track_name)
                track_data['lyrics'] = lyrics
            else:
                track_data['lyrics'] = None

            return track_data
        except Exception as e:
            print(f"Error processing track: {e}")
            return None

    def collect_playlist_data(self, playlist_id, output_file=DEFAULT_OUTPUT_FILE):
        """Collect data from a playlist and save to CSV"""
        print(f"Collecting tracks from playlist {playlist_id}...")
        tracks = self.get_playlist_tracks(playlist_id)

        print(f"Found {len(tracks)} tracks. Getting lyrics...")
        all_track_data = []

        for i, track_item in enumerate(tracks):
            track_data = self.get_track_data(track_item)
            if track_data:
                all_track_data.append(track_data)

            # Small delay to avoid hitting rate limits for both APIs
            if i % 20 == 0 and i > 0:
                print(f"Processed {i} tracks...")
                time.sleep(2)  # Increased sleep time

        # Create dataframe to save to csv
        df = pd.DataFrame(all_track_data)

        # Ensure directory exists
        os.makedirs(os.path.dirname(output_file), exist_ok=True)

        df.to_csv(output_file, index=False)
        print(f"Data saved to {output_file}")
        return df

    def search_and_collect(self, query, search_type='playlist', limit=3):
        """Search for playlists and collect their data"""
        try:
            results = self.sp.search(q=query, type=search_type, limit=limit)
            items = results.get(f"{search_type}s", {}).get('items', [])
        except Exception as e:
            print(f"Error searching for {search_type}s: {str(e)}")
            return None

        if not items:
            print(f"No {search_type}s found for query: {query}")
            return None

        print(f"\nFound {len(items)} {search_type}s matching '{query}':")
        for i, item in enumerate(items):
            # Validate item and its properties before accessing them
            if item is None:
                print(f"{i+1}. [Invalid playlist item]")
                continue

            try:
                name = item.get('name', '[No name]')
                owner_dict = item.get('owner', {})
                if owner_dict is None:
                    owner_dict = {}
                owner_display_name = owner_dict.get('display_name', '[Unknown]')
                item_id = item.get('id', '[No ID]')
                print(f"{i+1}. {name} by {owner_display_name} - {item_id}")
            except Exception as e:
                print(f"{i+1}. [Error displaying playlist: {str(e)}]")

        # Return the first valid result's ID
        if items:
            for item in items:
                if item is not None and isinstance(item, dict) and 'id' in item:
                    return item['id']
        return None

    def get_recommendations(self, seed_tracks=None, seed_artists=None, seed_genres=None, limit=50):
        """Get recommended tracks based on seeds"""
        recommendations = self.sp.recommendations(
            seed_tracks=seed_tracks,
            seed_artists=seed_artists,
            seed_genres=seed_genres,
            limit=limit
        )

        all_track_data = []
        for i, track in enumerate(recommendations['tracks']):
            track_data = {
                'id': track['id'],
                'name': track['name'],
                'popularity': track['popularity'],
                'explicit': track['explicit'],
                'duration_ms': track['duration_ms'],
                'album_name': track['album']['name'],
                'album_release_date': track['album']['release_date'],
                'artist_names': ', '.join([artist['name'] for artist in track['artists']]),
                'artist_ids': ', '.join([artist['id'] for artist in track['artists']])
            }

            # Get audio features
            features = self.get_track_features(track['id'])
            if features:
                track_data.update({
                    'danceability': features.get('danceability'),
                    'energy': features.get('energy'),
                    'key': features.get('key'),
                    'loudness': features.get('loudness'),
                    'mode': features.get('mode'),
                    'speechiness': features.get('speechiness'),
                    'acousticness': features.get('acousticness'),
                    'instrumentalness': features.get('instrumentalness'),
                    'liveness': features.get('liveness'),
                    'valence': features.get('valence'),
                    'tempo': features.get('tempo'),
                    'time_signature': features.get('time_signature')
                })

            all_track_data.append(track_data)

            # Add a small delay to avoid hitting rate limits
            if i % 50 == 0 and i > 0:
                time.sleep(1)

        return all_track_data


def main():
    parser = argparse.ArgumentParser(
        description='Collect data from Spotify API and Genius API')
    parser.add_argument(
        '--playlist', type=str, help='Playlist ID to collect data from')
    parser.add_argument(
        '--search', type=str, help='Search term for finding playlists')
    parser.add_argument(
        '--output', type=str, default=DEFAULT_OUTPUT_FILE, help='Output file path')
    parser.add_argument(
        '--genius_token', type=str, help='Genius API access token', required=False)
    parser.add_argument(
        '--genres', type=str, nargs='+', help='List of genres for recommendations')

    args = parser.parse_args()

    # Initialize collector with genius token
    collector = SpotifyDataCollector(genius_token=args.genius_token)

    playlist_id = args.playlist

    # If no playlist ID provided, search for one
    if not playlist_id and args.search:
        print(f"Searching for playlists matching: {args.search}")
        playlist_id = collector.search_and_collect(args.search)

    # If we have a playlist ID (either provided or found), collect data
    if playlist_id:
        df = collector.collect_playlist_data(playlist_id, args.output)
        print(f"Dataset shape: {df.shape}")
        print("\nSample data:")
        print(df.head())
    else:
        print(
            "No playlist ID provided or found. Use --playlist or --search")


if __name__ == "__main__":
    main()
