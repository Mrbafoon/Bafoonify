# %%
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import random
from dotenv import load_dotenv
import os
import streamlit as st
import json
import re
import unicodedata
from collections import Counter
import pandas as pd
import matplotlib.pyplot as plt

load_dotenv()
# Set your credentials here from spotify developer website placed inside a .env file, or replace with your actual credentials if you're not sharing your code.
SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")
SPOTIPY_REDIRECT_URI = os.getenv("SPOTIPY_REDIRECT_URI")

# Authentication
scope = "user-top-read playlist-read-private playlist-read-collaborative user-library-read user-library-modify playlist-modify-public playlist-modify-private"

sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=SPOTIPY_CLIENT_ID,
    client_secret=SPOTIPY_CLIENT_SECRET,
    redirect_uri=SPOTIPY_REDIRECT_URI,
    scope=scope
))



# Functions to get data from spotify and handle it
def paginate(input):
    items = input.get('items', [])
    while input.get('next'):
        input = sp.next(input)
        items.extend(input.get('items', []))
    return items
    
def normalize_text(value):
    # Normalize text so duplicate matching is case/punctuation/accent insensitive 
    if not value:
        return ""
    value = unicodedata.normalize("NFKD", str(value))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()

def get_user_playlists():
    output = sp.current_user_playlists(limit=50)
    return paginate(output)

def get_playlist_tracks(playlist_id):
    tracks = []
    output = sp.playlist_tracks(playlist_id)
    tracks.extend(output.get('items', []))
    while output.get('next'):
        output = sp.next(output)
        tracks.extend(output.get('items', []))
    return [t.get('track') for t in tracks if t.get('track')]

def get_playlist_tracks_items(playlist_id):
    fields = ("items(added_at,track(id,name,type,artists(id,name),album(name,release_date),duration_ms,popularity,external_urls,uri,is_local)),next")
    output = sp.playlist_items(playlist_id, limit=50, fields=fields)
    return paginate(output)

def get_playlist_snapshot_id(playlist_id):
    return sp.playlist(playlist_id, fields="snapshot_id").get("snapshot_id")

def get_consistent_playlist_tracks_items(playlist_id, attempts=2):
    for i in range(attempts):
        snapshot_before = get_playlist_snapshot_id(playlist_id)
        items = get_playlist_tracks_items(playlist_id)
        snapshot_after = get_playlist_snapshot_id(playlist_id)
        if snapshot_before == snapshot_after:
            return items, snapshot_after
        
    raise RuntimeError("Playlist changed during fetching. Try again.")

def get_top_artists(time_range, limit):
    return sp.current_user_top_artists(limit=limit, time_range=time_range).get("items", [])

def get_top_tracks(time_range, limit):
    return sp.current_user_top_tracks(limit=limit, time_range=time_range).get("items", [])  

def get_liked_tracks():
    output = sp.current_user_saved_tracks(limit=50)
    return paginate(output)

def first_artist_name(track):
    artists = track.get("artists") or []
    if not artists:
        return "Unknown Artist"
    return artists[0].get("name") or "Unknown Artist"

def all_artist_names(track):
    artists = track.get("artists") or []
    names = [a.get("name") for a in artists if a.get("name")]
    return ", ".join(names) if names else "Unknown Artist"

def load_spotify_extended_history(uploaded_files):
    rows = []

    required_fields = [
        "ts",
        "ms_played",
        "master_metadata_track_name",
        "master_metadata_album_artist_name"]

    for uploaded_file in uploaded_files:
        try:
            raw_data = json.load(uploaded_file)
        except Exception as exc: 
            st.warning(f"Could not parse {uploaded_file.name}. Make sure it's a valid JSON file from Spotify Extended History")
            continue
        
        if not isinstance(raw_data, list):
            st.error(f"Unexpected data format in {uploaded_file.name}")
            continue

        for row in raw_data:
            if not all(field in row for field in required_fields):
                continue

            if row["master_metadata_track_name"] is None:
                continue
            rows.append({
                "ts": row["ts"],
                "ms_played": row["ms_played"],
                "track_name": row["master_metadata_track_name"],
                "artist_name": row["master_metadata_album_artist_name"],
                "album_name": row.get("master_metadata_album_name"),
                "spotify_track_uri": row.get("spotify_track_uri")})
                
    return pd.DataFrame(rows)

def remove_extra_playlist_duplicates(playlist_id, playlist_rows, rows_to_remove, snapshot_id=None):
    if rows_to_remove.empty:
        return None

    ordered_rows = playlist_rows.sort_values("spotify_position").copy()
    selected_rows = rows_to_remove.sort_values("spotify_position").copy()
    if selected_rows["uri"].isna().any():
        raise RuntimeError("Some songs to remove have missing URIs.")
    
    positions_to_remove = {
        int(position) for position in selected_rows["spotify_position"].tolist()
        if pd.notna(position)}

    if not positions_to_remove:
        return None
    
    known_positions = set(ordered_rows["spotify_position"].astype(int))
    if not positions_to_remove.issubset(known_positions):
        raise RuntimeError("Some positions to remove are not in the playlist.")
    
    uri_by_position = {int(row["spotify_position"]): row["uri"] 
        for i, row in ordered_rows.iterrows()}

    for i, row in selected_rows.iterrows():
        position = int(row["spotify_position"])
        if uri_by_position[position] != row["uri"]:
            raise RuntimeError("URI mismatch for position.")
    
    current_snapshot_id = get_playlist_snapshot_id(playlist_id)
    if snapshot_id and current_snapshot_id != snapshot_id:
        raise RuntimeError("Playlist has been modified since the last snapshot. Try again.")
# Spotify's current remove-items endpoint removes every occurrence of a URI, 
# so we put songs back into the playlist that we're not supposed to be removed.
    target_uris = list(dict.fromkeys(selected_rows["uri"].tolist()))
    if any(not str(uri).startswith("spotify:track:") for uri in target_uris):
        raise RuntimeError("One or more selected items can't be removed.")

    retained_rows = ordered_rows[
        ordered_rows["uri"].isin(target_uris)
        & ~ordered_rows["spotify_position"].astype(int).isin(positions_to_remove)].copy()

    next_snapshot_id = snapshot_id
    for index in range(0, len(target_uris), 100):
        response = sp.playlist_remove_all_occurrences_of_items(
            playlist_id,
            target_uris[index:index + 100],
            snapshot_id=next_snapshot_id)
        if response and response.get("snapshot_id"):
            next_snapshot_id = response["snapshot_id"]

    sorted_removed_positions = sorted(positions_to_remove)
    for i, row in retained_rows.sort_values("spotify_position").iterrows():
        original_position = int(row["spotify_position"])
        removed_before = sum(
            position < original_position
            for position in sorted_removed_positions)
        final_position = original_position - removed_before
        sp.playlist_add_items(
            playlist_id,
            [row["uri"]],
            position=final_position)

    return len(positions_to_remove)

def get_extra_duplicate_rows(df):

    counts = df["duplicate_key"].value_counts()
    duplicate_keys = counts[counts > 1].index
    duplicates = df[df["duplicate_key"].isin(duplicate_keys)].copy()

    if duplicates.empty:
        return pd.DataFrame()

    duplicates = duplicates.sort_values(["duplicate_key", "spotify_position"])
    # Keep the first copy of each duplicate group and remove the rest
    duplicates["duplicate_number"] = duplicates.groupby("duplicate_key").cumcount()

    return duplicates[duplicates["duplicate_number"] > 0].copy()

def remove_extra_liked_song_duplicates(rows_to_remove):
    track_ids = []

    for i, row in rows_to_remove.iterrows():
        track_id = row.get("track_id")

        if pd.notna(track_id):
            track_ids.append(track_id)

    if not track_ids:
        return None

    for i in range(0, len(track_ids), 40):
        batch = track_ids[i:i + 40]
        sp.current_user_saved_tracks_delete(tracks=batch)          
           
def show_duplicates(df, playlist_id=None, source_type=None, snapshot_id=None):
    if df.empty:
        st.warning("No tracks found to scan.")
        return

    counts = df["duplicate_key"].value_counts()
    duplicate_keys = counts[counts > 1].index
    duplicates = df[df["duplicate_key"].isin(duplicate_keys)].copy()
    st.metric("Tracks scanned", len(df))
    st.metric("Duplicate groups found", len(duplicate_keys))

    if duplicates.empty:
        st.success("No duplicates found.")
        return

    summary = (duplicates.groupby(["duplicate_key", "track_name", "first_artist"], as_index=False).agg(
            copies = ("track_name", "size"),
            albums = ("album", lambda x: ", ".join(sorted(set(str(v) for v in x if pd.notna(v))))),
            positions = ("position", lambda x: ", ".join(map(str, x))),).sort_values("copies", ascending=False))

    st.subheader("Duplicates Summary")
    st.dataframe(summary[["track_name", "first_artist", "copies", "albums", "positions"]],width='stretch')   

    rows_to_remove = get_extra_duplicate_rows(df)
    if rows_to_remove.empty:
        return

    st.subheader("Remove Duplicates")
    if source_type == "Playlist":
        st.write("Select the duplicate occurrences you want to remove.")

        playlist_remove_options = duplicates.sort_values(["duplicate_key", "spotify_position"]).copy()
        default_remove_positions = set(rows_to_remove["spotify_position"].astype(int))
        playlist_remove_options["delete"] = (playlist_remove_options["spotify_position"]
                                             .astype(int).isin(default_remove_positions))

        editor_columns = [
            "delete",
            "position",
            "track_name",
            "artists",
            "album",
            "duration_min",
            "popularity",
            "added_at",
            "spotify_url"]
        editor_columns = [
            col for col in editor_columns
            if col in playlist_remove_options.columns]

        edited_rows = st.data_editor(
            playlist_remove_options[editor_columns],
            column_config = {
                "delete": st.column_config.CheckboxColumn(
                    "Delete",
                    help = "Check this song to remove it.",
                    default = False),
                "spotify_url": st.column_config.LinkColumn("Spotify URL")},
            disabled = [col for col in editor_columns if col != "delete"],
            hide_index = True,
            width = 'stretch',
            key = f"playlist_duplicates_delete_editor_{playlist_id}_{snapshot_id}")

        selected_positions = set(
            edited_rows.loc[edited_rows["delete"] == True, "position"]
            .astype(int))
        final_rows_to_remove = playlist_remove_options[
            playlist_remove_options["position"].astype(int)
            .isin(selected_positions)].copy()

        st.write(f"Selected {len(final_rows_to_remove)} song occurrence(s) to remove.")

        if not final_rows_to_remove.empty:
            selected_counts = final_rows_to_remove.groupby("duplicate_key").size()
            duplicate_counts = duplicates.groupby("duplicate_key").size()
            fully_selected_groups = [
                key for key, count in selected_counts.items()
                if count == duplicate_counts.get(key)]
            if fully_selected_groups:
                st.warning("Every copy is selected in one or more duplicate groups; those songs will be removed completely.")

        confirm = st.checkbox("Yes, remove the selected songs",key=f"confirm_remove_playlist_dupes_{playlist_id}")

        if st.button(
                "Remove Selected Playlist Duplicates",
                key = f"remove_selected_playlist_dupes_{playlist_id}",
                disabled = not confirm or final_rows_to_remove.empty):
            with st.spinner("Removing selected duplicate songs..."):
                try:
                    removed_count = remove_extra_playlist_duplicates(
                        playlist_id,
                        df,
                        final_rows_to_remove,
                        snapshot_id=snapshot_id)

                    st.success(f"Removed {removed_count} selected songs")

                    st.session_state.pop("duplicate_scan", None)
                    st.rerun()

                except Exception as e:
                    st.error("Could not remove duplicate songs.")
                    st.exception(e)

    elif source_type == "Liked Songs":
        st.write("Select which songs you want to remove from your liked songs. (40 songs per batch)w")
        
        liked_remove_options = rows_to_remove.copy()
        liked_remove_options["delete"] = True

        editor_columns = [
            "delete",
            "position",
            "track_name",
            "artists",
            "album",
            "duration_min",
            "popularity",
            "added_at",
            "spotify_url",
            "track_id",]

        editor_columns = [col for col in editor_columns if col in liked_remove_options.columns]

        edited_rows = st.data_editor(
            liked_remove_options[editor_columns],
            column_config={
                "delete": st.column_config.CheckboxColumn("Delete", 
                    help="Uncheck this song if you want to keep it.",
                    default=True), "spotify_url": st.column_config.LinkColumn("Spotify URL")},
            disabled=[col for col in editor_columns if col != "delete"],
            hide_index=True,
            width='stretch',
            key="liked_duplicates_delete_editor")

        final_rows_to_remove = edited_rows[edited_rows["delete"] == True].copy()

        st.write(f"Selected {len(final_rows_to_remove)} song(s) to remove.")

        confirm = st.checkbox("OK, remove these songs.", key="confirm_remove_liked_dupes",)

        if st.button("Remove Selected Liked Song Duplicates",key="remove_selected_liked_dupes",disabled=not confirm or final_rows_to_remove.empty,):
            with st.spinner("Removing selected liked songs..."):
                try:
                    remove_extra_liked_song_duplicates(final_rows_to_remove)

                    st.success(f"Removed {len(final_rows_to_remove)} selected songs.")
                    st.session_state.pop("duplicate_scan", None)
                    st.rerun()

                except Exception as e:
                    st.error("Could not remove selected liked songs.")
                    st.exception(e)


    else:
        return



# to dataframe functions
def track_items_to_df(items, source_name):
    # Convert playlist item or song item objects into a dataframe
    rows = []

    for index, item in enumerate(items):
        track = item.get("track") if isinstance(item, dict) else None
        if not track or track.get("type") not in (None, "track"):
            continue

        track_name = track.get("name") or "Unknown Track"
        first_artist = first_artist_name(track)
        artists = all_artist_names(track)
        album = track.get("album") or {}
        external_urls = track.get("external_urls") or {}

        rows.append({
                "source": source_name,
                "position": index+1,               # displayed position
                "spotify_position": index,         # for actual position used in spotify api calls (0 indexed)
                "uri": track.get("uri"),
                "track_id": track.get("id"),
                "track_name": track_name,
                "first_artist": first_artist,
                "artists": artists,
                "album": album.get("name"),
                "release_date": album.get("release_date"),
                "duration_min": round((track.get("duration_ms") or 0) / 60000, 2),
                "popularity": track.get("popularity"),
                "added_at": item.get("added_at"),
                "spotify_url": external_urls.get("spotify"),
                "duplicate_key": f"{normalize_text(track_name)}|{normalize_text(first_artist)}"})
    
    return pd.DataFrame(rows)

def build_monthly_listening_df(df, minimum_seconds=30, exclude_skipped=False):
    if df.empty:
        return pd.DataFrame()
    df = df.copy()

    df["played_at"] = pd.to_datetime(df["ts"], errors="coerce", utc=True)
    df["ms_played"] = pd.to_numeric(df["ms_played"], errors="coerce").fillna(0)

    df = df.dropna(subset=["played_at"])

    if exclude_skipped and "skipped" in df.columns:
        df = df[df["skipped"] != True]

    df["month"] = df["played_at"].dt.to_period("M").dt.to_timestamp()

    monthly_listening = df.groupby("month").agg(
        total_minutes=("ms_played", lambda x: x.sum() / 60000),
        unique_tracks=("track_name", "nunique"),
        unique_artists=("artist_name", "nunique"),
        track_count=("spotify_track_uri", "count")
    ).reset_index().sort_values("month")

    monthly_listening["hours_played"] = (monthly_listening["total_minutes"] / 60).round(2)
    monthly_listening["month_label"] = monthly_listening["month"].dt.strftime("%Y-%m")
    return monthly_listening



# ui functions to display via streamlit
def guess_artist_ui():
    playlists = get_user_playlists()
    if not playlists:
        return

    playlist_names = [p.get("name", "Unknown") for p in playlists]
    chosen_name = st.selectbox("Choose a playlist", playlist_names)
    chosen = playlists[playlist_names.index(chosen_name)]

    if "game_song" not in st.session_state:
        st.session_state.game_song = None
        st.session_state.guess = ""

    if st.button("Pick Random Song", key="pick_song"):
        all_tracks = get_playlist_tracks(chosen['id'])
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
                st.success("Correct ദ്ദി( • ᴗ - ) ✧")
                st.session_state.game_song = None
            else:
                st.error(f"Incorrect (╥﹏╥) | The artist is: {answer}")


def top_artists_ui():
# short term ~ 4 weeks, medium term ~ 6 months, long term ~ 1 year, I believe
    time_range = st.selectbox("Select Time Range", ["short_term", "medium_term", "long_term"])
    if st.button("Show Top Artists", key="show_artists"):
        top_artists = get_top_artists(time_range=time_range, limit=10)
        for i, artist in enumerate(top_artists, 1):
            st.write(f"{i}. {artist.get('name')}")


def top_tracks_ui():
    time_range = st.selectbox("Select Time Range", ["short_term", "medium_term", "long_term"], key="tracks_time")
    if st.button("Show Top Tracks", key="show_tracks"):
        top_tracks = get_top_tracks(time_range=time_range, limit=10)
        for i, track in enumerate(top_tracks, 1):
            st.write(f"{i}. {track.get('name')} - {track.get('artists', [{}])[0].get('name')}")


def duplicate_song_checker_ui():
    st.write("This tool checks a playlist for duplicate songs based on the name of the song and the first artist listed under the song. MAKE SURE YOU REFRESH SPOTIFY DATA BEFORE DELETING SONGS.")

    source_type = st.radio("Check Duplicates In", ["Playlist", "Liked Songs"],horizontal=True)
    if source_type == "Playlist":
        playlists = get_user_playlists()
        if not playlists:
            return
        
        playlist_names = [p.get("name", "Unknown") for p in playlists]
        chosen_name = st.selectbox("Choose a playlist to check", playlist_names, key="dupe_playlist")
        chosen = playlists[playlist_names.index(chosen_name)]

        if st.button("Find Duplicate Songs in Playlist", key="find_playlist_dupes"):
            with st.spinner("Checking for duplicates..."):
                items, snapshot_id = get_consistent_playlist_tracks_items(chosen['id'])
                df = track_items_to_df(items, source_name=chosen_name)

                st.session_state["duplicate_scan"] = {
                    "source_type": "playlist",
                    "playlist_id": chosen['id'],
                    "playlist_name": chosen_name,   
                    "df": df,
                    "snapshot_id": snapshot_id}
                
        scan = st.session_state.get("duplicate_scan") 

        if (scan and scan.get("source_type") == "playlist" and scan.get("playlist_id") == chosen['id']):
            show_duplicates(
                scan.get("df"), 
                snapshot_id=scan.get("snapshot_id"),
                playlist_id=scan.get("playlist_id"), 
                source_type="Playlist")
                
    elif source_type == "Liked Songs":
        if st.button("Find Duplicate Liked Songs", key="find_liked_dupes"):
            with st.spinner("Checking for duplicates..."):
                items = get_liked_tracks()
                df = track_items_to_df(items, source_name="Liked Songs")
                
                st.session_state["duplicate_scan"] = {
                    "source_type": "Liked Songs",
                    "df": df}
        
        scan = st.session_state.get("duplicate_scan")
        if scan and scan.get("source_type") == "Liked Songs":
            show_duplicates(scan.get("df"), source_type="Liked Songs")

def top_genres_ui():
    time_range = st.selectbox("Select Time Range", ["short_term", "medium_term", "long_term"], key="genre_time")
    num_artists = st.slider("Number of Top Artists to Analyze", min_value=1, max_value=50, value=20, step=1, key="genre_artist_count")
    num_genres = st.slider("Number of Top Genres to Display", min_value=1, max_value=30, value=10, step=1, key="genre_count")

    if st.button("Top Genres", key="show_genres"):
        with st.spinner("Analyzing top genres..."):
            top_artists = get_top_artists(time_range=time_range, limit=num_artists)
            genre_counts = Counter()

            for artist in top_artists:
                genre_counts.update(artist.get("genres") or [])

            if not genre_counts:
                st.warning("No genres found.")
                return

            genre_df = pd.DataFrame(genre_counts.most_common(num_genres), columns=["Genre", "Artist Count"]).sort_values("Artist Count", ascending=True)

            st.subheader("Top Genres")
            fig, ax = plt.subplots(figsize=(10,7))
            ax.barh(genre_df["Genre"], genre_df["Artist Count"], color="skyblue")
            ax.set_xlabel("Genre")
            ax.set_ylabel("Artist Count")
            ax.set_title("Top Genres")
            st.pyplot(fig)  


def monthly_listening_ui():
    st.write("Upload your Spotify Extended Streaming History JSON files to see your monthly listening trends. " \
    "You can download these files from the Spotify website, go to account settings and under 'Account Privacy' there is a 'Download Your Data' section.")

    uploaded_files = st.file_uploader("Upload Spotify Extended Streaming History JSON files", type=["json"], accept_multiple_files=True, key="history_upload")

    if not uploaded_files:
        st.info("Upload one or more JSON files.")
        return

    minimum_seconds = st.slider("Ignore plays under how many seconds?", min_value=0, max_value=300, value=30, step=5, key="min_seconds")   
    exclude_skipped = st.checkbox("Exclude skipped tracks (if your data includes this)", value=False , key="exclude_skipped")

    history_df = load_spotify_extended_history(uploaded_files)
    if history_df.empty:
        st.warning("No valid listening data found in uploaded files.")
        return

    monthly_df = build_monthly_listening_df(history_df, minimum_seconds=minimum_seconds, exclude_skipped=exclude_skipped)
    if monthly_df.empty:
        st.warning("No listening data after applying filters.")
        return
    
    total_hours = monthly_df["hours_played"].sum()
    total_plays = monthly_df["track_count"].sum()

    col1,col2,col3 = st.columns(3)
    col1.metric("Total Hours Played", f"{total_hours:.1f}")
    col2.metric("Total Plays", f"{total_plays}")
    col3.metric("Months Analyzed", len(monthly_df))

    st.subheader("Monthly Listening Trends")
    chart_df = monthly_df.set_index("month_label")[["track_count"]]
    chart_df2 = monthly_df.set_index("month_label")[["hours_played"]]

    st.line_chart(chart_df, y_label="Play Count")
    st.line_chart(chart_df2, y_label="Hours Played", color="orange")
    st.subheader("Monthly Listening Table")

    display_df = monthly_df[["month_label", "hours_played", "track_count", "unique_tracks", "unique_artists"]].copy()
    display_df["hours_played"] = display_df["hours_played"].round(2)

    st.dataframe(display_df.rename(columns={
        "month_label": "Month",
        "hours_played": "Hours Played",
        "track_count": "Play Count",
        "unique_tracks": "Unique Tracks",
        "unique_artists": "Unique Artists",
    }), width='stretch')



# streamlit page functions
if st.sidebar.button("Refresh Spotify Data"):
    for key in ["liked_tracks","playlists","top_artists","playlist_tracks"]:
        st.session_state.pop(key, None)
    st.rerun()

st.title("Bafoonify")

menu = st.sidebar.selectbox("Choose Mode", ["Artist Guessing Game", "Top Artists", "Top Tracks", "Top Genres", "Monthly Listening History", "Duplicate Song Checker"])
if menu == "Artist Guessing Game":
    st.header("Artist Guessing Game")
    guess_artist_ui()
elif menu == "Top Artists":
    st.header("Your Top Artists")
    top_artists_ui()
elif menu == "Top Tracks":
    st.header("Your Top Tracks")
    top_tracks_ui()
elif menu == "Top Genres":
    st.header("Your Top Genres")
    top_genres_ui()
elif menu == "Monthly Listening History":
    st.header("Monthly Listening History")
    monthly_listening_ui()
elif menu == "Duplicate Song Checker":
    st.header("Duplicate Song Checker")
    duplicate_song_checker_ui()





