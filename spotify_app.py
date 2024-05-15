import streamlit as st
import requests
import pandas as pd
import plotly.express as px
from st_aggrid import AgGrid

# Obtener las credenciales de los secretos
client_id = st.secrets["client_id"]
client_secret = st.secrets["client_secret"]
opencage_api_key = st.secrets["opencage_api_key"]

# Funciones para obtener datos de Spotify
def get_access_token(client_id, client_secret):
    auth_url = 'https://accounts.spotify.com/api/token'
    auth_response = requests.post(auth_url, {
        'grant_type': 'client_credentials',
        'client_id': client_id,
        'client_secret': client_secret,
    })
    auth_response_data = auth_response.json()
    if 'access_token' in auth_response_data:
        return auth_response_data['access_token']
    else:
        st.error("Error al obtener el token de acceso")
        return None

def make_request(url, headers, params=None, max_retries=3, backoff_factor=1.0):
    retries = 0
    while retries < max_retries:
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            return response.json()
        elif response.status_code in [429, 500, 502, 503, 504]:
            retries += 1
            sleep_time = backoff_factor * (2 ** retries)
            st.warning(f"Error {response.status_code}: {response.text}. Reintentando en {sleep_time} segundos...")
            time.sleep(sleep_time)
        else:
            st.error(f"Error {response.status_code}: {response.text}")
            response.raise_for_status()
    raise Exception(f"Failed to get a valid response after {max_retries} retries.")

def get_artist_data(artist_name, client_id, client_secret):
    access_token = get_access_token(client_id, client_secret)
    if not access_token:
        return None

    headers = {'Authorization': f'Bearer {access_token}'}
    BASE_URL = 'https://api.spotify.com/v1/'

    # Buscar el artista
    search_url = f'{BASE_URL}search'
    search_params = {'q': artist_name, 'type': 'artist', 'limit': 1}
    search_response = make_request(search_url, headers, search_params)
    
    if search_response and search_response['artists']['items']:
        artist = search_response['artists']['items'][0]
        artist_id = artist['id']
        artist_popularity = artist['popularity']
        artist_followers = artist['followers']['total']
    else:
        st.error(f"No artist found with name {artist_name}")
        return None
    
    # Obtener álbumes del artista
    albums_url = f'{BASE_URL}artists/{artist_id}/albums'
    albums_data = make_request(albums_url, headers, params={'include_groups': 'album', 'limit': 50})
    albums = [album for album in albums_data['items'] if album['album_group'] == 'album' and album['album_type'] == 'album']

    data = []
    for album in albums:
        album_name = album['name']
        tracks_url = f'{BASE_URL}albums/{album["id"]}/tracks'
        tracks_data = make_request(tracks_url, headers)
        tracks = tracks_data['items']
        track_ids = [track['id'] for track in tracks]
        features_url = f'{BASE_URL}audio-features'
        features_data = make_request(features_url, headers, params={'ids': ','.join(track_ids)})
        
        features = features_data['audio_features']
        for track, feature in zip(tracks, features):
            if feature:
                track_info_url = f'{BASE_URL}tracks/{track["id"]}'
                track_info = make_request(track_info_url, headers)
                feature.update({
                    'track_name': track['name'],
                    'album_name': album_name,
                    'release_date': album['release_date'],
                    'release_date_precision': album['release_date_precision'],
                    'duration_ms': track['duration_ms'],
                    'popularity': track_info['popularity']
                })
                data.append(feature)

    if not data:
        st.error("No data collected")
        return None

    df = pd.DataFrame(data)

    def handle_date_precision(row):
        if row['release_date_precision'] == 'year':
            return pd.to_datetime(row['release_date'], format='%Y')
        elif row['release_date_precision'] == 'month':
            return pd.to_datetime(row['release_date'], format='%Y-%m')
        else:
            return pd.to_datetime(row['release_date'], format='%Y-%m-%d')

    df['release_date'] = df.apply(handle_date_precision, axis=1)
    df = df.sort_values(by='release_date')
    df = df[~df['track_name'].str.contains('Live|Mix|Track')]
    
    # Obtener ubicación del artista
    search_url = f'https://musicbrainz.org/ws/2/artist/?query={artist_name}&fmt=json'
    mb_response = make_request(search_url, {}, params={})
    if not mb_response or not mb_response['artists']:
        st.error("No artist found on MusicBrainz")
        return df, artist, None

    artist_info = mb_response['artists'][0]
    if 'country' in artist_info:
        country = artist_info['country']
        location = country
    else:
        location = 'Unknown'
    
    geocode_url = "https://api.opencagedata.com/geocode/v1/json"
    geocode_params = {
        'q': location,
        'key': opencage_api_key,
        'limit': 1
    }
    geocode_response = make_request(geocode_url, {}, params=geocode_params)
    if geocode_response and geocode_response['results']:
        lat = geocode_response['results'][0]['geometry']['lat']
        lon = geocode_response['results'][0]['geometry']['lng']
    else:
        lat, lon = 0, 0
    
    artist_location = {
        'name': artist_info['name'],
        'popularity': artist_popularity,
        'followers': artist_followers,
        'lat': lat,
        'lon': lon
    }
    
    return df, artist, artist_location

# Interfaz de usuario con Streamlit
st.title("Spotify Artist Data Explorer")

client_id = st.text_input("Client ID", value='fced6aa8e6c84f49b80df73470fc36c7')
client_secret = st.text_input("Client Secret", value='fe58d684f87c4a72861faafdb10a466a', type="password")
artist_name = st.text_input("Enter Artist Name", value='Led Zeppelin')

if st.button("Search"):
    if not client_id or not client_secret or not artist_name:
        st.error("Please provide all required inputs.")
    else:
        with st.spinner('Fetching data...'):
            data = get_artist_data(artist_name, client_id, client_secret)
            if data:
                df, artist, artist_location = data
                st.session_state['df'] = df
                st.session_state['artist'] = artist
                st.session_state['artist_location'] = artist_location

if 'df' in st.session_state and 'artist' in st.session_state and 'artist_location' in st.session_state:
    df = st.session_state['df']
    artist = st.session_state['artist']
    artist_location = st.session_state['artist_location']
    
    st.success(f"Data for {artist['name']} fetched successfully!")
    
    # Mostrar datos del artista
    st.write(f"**Artist:** {artist['name']}")
    st.write(f"**Followers:** {artist['followers']['total']}")
    st.write(f"**Popularity:** {artist['popularity']}")

    # Mostrar tabla de datos
    st.write("### Songs Data")
    AgGrid(df[['track_name', 'album_name', 'release_date', 'duration_ms', 'popularity']])

    # Crear las gráficas de dispersión para cada característica
    features = ['acousticness', 'danceability', 'energy', 'speechiness', 'liveness', 'instrumentalness']
    scatter_plots = {feature: px.scatter(
        df,
        x='valence',
        y=feature,
        size='duration_ms',
        color='album_name',
        hover_data=['track_name', 'duration_ms', 'popularity'],
        title=f'Valence vs {feature.capitalize()} of {artist["name"]} songs'
    ) for feature in features}

    # Carrusel de gráficos
    st.write("### Valence vs Different Features")
    selected_feature = st.selectbox("Select Feature", features)
    st.plotly_chart(scatter_plots[selected_feature])

    # Mostrar mapa de la ubicación del artista
    if artist_location:
        st.write("### Artist Origin Map")
        artist_df = pd.DataFrame([artist_location])
        fig_map = px.scatter_geo(
            artist_df,
            lat='lat',
            lon='lon',
            text='name',
            size='popularity',
            title='Artist Origin Map',
            hover_name='name',
            hover_data={'popularity': True, 'followers': True, 'lat': False, 'lon': False},
            projection='natural earth'
        )
        st.plotly_chart(fig_map)
    else:
        st.warning("Could not retrieve artist location.")
