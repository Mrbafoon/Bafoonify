#!/usr/bin/env python
# coding: utf-8

# In[ ]:


import spotipy
from spotipy.oauth2 import SpotifyOAuth
import random
from dotenv import load_dotenv
import os

#enviornment variables
load_dotenv()

#Set your credentials here from spotify developer website, you can use your own .env file if you'd like.
SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")      
SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")  
SPOTIPY_REDIRECT_URI = os.getenv("SPOTIPY_REDIRECT_URI")


#Authentication
scope = "user-top-read playlist-read-private" 

sp = spotipy.Spotify(auth_manager=SpotifyOAuth(

    client_id=SPOTIPY_CLIENT_ID,
    client_secret=SPOTIPY_CLIENT_SECRET,
    redirect_uri=SPOTIPY_REDIRECT_URI,

    scope=scope
))

def Guess_Artist():
    #List your playlists and let you choose one
    playlists = sp.current_user_playlists()
    playlist_map = {i: playlist for i, playlist in enumerate(playlists['items'])}

    print("Your Playlists:")
    for i, playlist in playlist_map.items():
        print(f"{i}: {playlist['name']} ({playlist['tracks']['total']} tracks)")

    chosen_index = int(input("Choose a playlist number: "))
    chosen_playlist = playlist_map[chosen_index]


    #Get all tracks in the chosen playlist
    tracks = []
    results = sp.playlist_tracks(chosen_playlist['id'])
    tracks.extend(results['items'])

    while results['next']:
        results = sp.next(results)
        tracks.extend(results['items'])

    #Filter out tracks with missing info
    valid_tracks = [t['track'] for t in tracks if t['track'] and t['track']['artists']]

    #Pick a random song and run the quiz
    random_song = random.choice(valid_tracks)
    song_name = random_song['name']
    artist_name = random_song['artists'][0]['name']

    #quiz question
    print(f"\nWho is the artist of the song: \"{song_name}\"?")
    guess = input("Your answer: ").strip()

    if guess.lower() == artist_name.lower():
        print("Correct ദ്ദി( • ᴗ - ) ✧")
    else:
        print(f"Incorrect. The artist is: {artist_name}")
    pass 


def view_artists():
    return sp.current_user_top_artists(limit=10)

def view_songs():
    return sp.current_user_top_tracks(limit=10)

def main_menu():
    while True:
        print("\nSpotify App:")
        print("1. Guess the Artist")
        print("2. View Top Artists")
        print("3. View Top Songs")
        print("4. Exit")

        choice = input("Choose an option: ")

        if choice == "1":
            Guess_Artist()
        elif choice == "2":
            stats = view_artists()

            print("\nYour Top Artists:")
            for i, artist in enumerate(stats["items"], 1):
                print(f"{i}. {artist['name']}")
        elif choice == "3":
            stats = view_songs()

            print("\nYour Top Songs:")
            for i, track in enumerate(stats["items"], 1):
                print(f"{i}. {track['name']}")
        elif choice == "4":
            break
        else:
            print("Only accepts 1, 2, 3, or 4 as input.")

main_menu()


# 

# In[ ]:




