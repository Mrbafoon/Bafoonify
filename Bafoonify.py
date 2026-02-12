#!/usr/bin/env python
# coding: utf-8

# In[ ]:


import spotipy
from spotipy.oauth2 import SpotifyOAuth
import random
from dotenv import load_dotenv
import os
import streamlit as st

# environment variables
load_dotenv()

# Set your credentials here from spotify developer website or .env file
SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")
SPOTIPY_REDIRECT_URI = os.getenv("SPOTIPY_REDIRECT_URI")

# Authentication
scope = "user-top-read playlist-read-private"

sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=SPOTIPY_CLIENT_ID,
    client_secret=SPOTIPY_CLIENT_SECRET,
    redirect_uri=SPOTIPY_REDIRECT_URI,
    scope=scope
))


def _get_playlist_tracks(playlist_id):
    tracks = []
    results = sp.playlist_tracks(playlist_id)
    tracks.extend(results.get('items', []))
    while results.get('next'):
        results = sp.next(results)
        tracks.extend(results.get('items', []))
    return [t.get('track') for t in tracks if t.get('track')]


def Guess_Artist_ui():
    playlists_resp = sp.current_user_playlists(limit=50)
    playlists = playlists_resp.get("items", [])

    if not playlists:
        st.info("No playlists found for your account.")
        return

    playlist_names = [p.get("name", "Unknown") for p in playlists]
    chosen_name = st.selectbox("Choose a playlist", playlist_names)
    chosen = playlists[playlist_names.index(chosen_name)]

    if "game_song" not in st.session_state:
        st.session_state.game_song = None
        st.session_state.guess = ""

    if st.button("Pick Random Song", key="pick_song"):
        all_tracks = _get_playlist_tracks(chosen['id'])
        valid_tracks = [t for t in all_tracks if t and t.get('artists')]
        if not valid_tracks:
            st.warning("No valid tracks found in this playlist.")
        else:
            song = random.choice(valid_tracks)
            st.session_state.game_song = {"name": song.get('name'), "artist": song.get('artists', [{}])[0].get('name')}
            st.session_state.guess = ""

    if st.session_state.game_song:
        st.write("**Guess the artist**")
        st.write(f"Song: {st.session_state.game_song['name']}")
        st.session_state.guess = st.text_input("Your answer", value=st.session_state.guess, key="guess_input")
        if st.button("Submit Guess", key="submit_guess"):
            answer = st.session_state.game_song.get('artist') or "Unknown"
            if st.session_state.guess.strip().lower() == answer.strip().lower():
                st.success("Correct! 🎉")
                st.session_state.game_song = None
            else:
                st.error(f"Incorrect. The artist is: {answer}")


def Top_Artists_ui():
    time_range = st.selectbox("Select Time Range", ["short_term", "medium_term", "long_term"])
    if st.button("Show Top Artists", key="show_artists"):
        top_artists = sp.current_user_top_artists(limit=10, time_range=time_range)
        for i, artist in enumerate(top_artists.get("items", []), 1):
            st.write(f"{i}. {artist.get('name')}")


def Top_Tracks_ui():
    time_range = st.selectbox("Select Time Range", ["short_term", "medium_term", "long_term"], key="tracks_time")
    if st.button("Show Top Tracks", key="show_tracks"):
        top_tracks = sp.current_user_top_tracks(limit=10, time_range=time_range)
        for i, track in enumerate(top_tracks.get("items", []), 1):
            st.write(f"{i}. {track.get('name')} - {track.get('artists', [{}])[0].get('name')}")


st.title("🎵 Spotify Game & Stats App")

menu = st.sidebar.selectbox("Choose Mode", ["Artist Guessing Game", "Top Artists", "Top Tracks"])
if menu == "Artist Guessing Game":
    st.header("Artist Guessing Game")
    Guess_Artist_ui()
elif menu == "Top Artists":
    st.header("Your Top Artists")
    Top_Artists_ui()
elif menu == "Top Tracks":
    st.header("Your Top Tracks")
    Top_Tracks_ui()



# 

# In[ ]:




