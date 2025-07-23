#!/usr/bin/env python
# coding: utf-8

# In[ ]:


import spotipy
from spotipy.oauth2 import SpotifyOAuth
import random
from dotenv import load_dotenv
import os

load_dotenv() #enviornment variables


# Set your credentials here from spotify developer website

SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")      

SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")  

SPOTIPY_REDIRECT_URI = os.getenv("SPOTIPY_REDIRECT_URI")


# Start authentication

scope = "playlist-read-private"

sp = spotipy.Spotify(auth_manager=SpotifyOAuth(

    client_id=SPOTIPY_CLIENT_ID,

    client_secret=SPOTIPY_CLIENT_SECRET,

    redirect_uri=SPOTIPY_REDIRECT_URI,

    scope=scope

))


# List your playlists and let you choose one

playlists = sp.current_user_playlists()

playlist_map = {i: playlist for i, playlist in enumerate(playlists['items'])}

print("Your Playlists:")

for i, playlist in playlist_map.items():

    print(f"{i}: {playlist['name']} ({playlist['tracks']['total']} tracks)")


chosen_index = int(input("Choose a playlist number: "))

chosen_playlist = playlist_map[chosen_index]


# Get all tracks in the chosen playlist

tracks = []

results = sp.playlist_tracks(chosen_playlist['id'])

tracks.extend(results['items'])

while results['next']:

    results = sp.next(results)

    tracks.extend(results['items'])


# Filter out tracks with missing info

valid_tracks = [t['track'] for t in tracks if t['track'] and t['track']['artists']]


# Pick a random song and run the quiz

random_song = random.choice(valid_tracks)

song_name = random_song['name']

artist_name = random_song['artists'][0]['name']


# Ask the quiz question

print(f"\nWho is the artist of the song: \"{song_name}\"?")

guess = input("Your answer: ").strip()


if guess.lower() == artist_name.lower():

    print("Correct! 🎉")

else:

    print(f"Incorrect. The artist is: {artist_name}")

