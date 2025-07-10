#Prod
from datetime import datetime, timedelta
import time
import streamlit as st
import requests
import pandas as pd
from PIL import Image
import pillow_heif
import os
import base64
from supabase import create_client, Client
from pillow_heif import register_heif_opener
from dateutil import parser
import pytz
import re
from streamlit_calendar import calendar
import cloudinary
import cloudinary.uploader

register_heif_opener()

# Use secrets from Streamlit Cloud
ACCESS_TOKEN = st.secrets["ACCESS_TOKEN"]
IG_USER_ID = st.secrets["IG_USER_ID"]
API_VERSION = st.secrets["API_VERSION"]
CLOUD_NAME = st.secrets["CLOUD_NAME"]
API_KEY = st.secrets["API_KEY"]
API_SECRET = st.secrets["API_SECRET"]
OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
BASE_URL = f"https://graph.facebook.com/{API_VERSION}/{IG_USER_ID}/insights"
SUPABASE_URL = st.secrets["SUPABASE_URL"]
USERNAME = st.secrets["USER_NAME"]
PASSWORD = st.secrets["USER_PASSWORD"]
SUPABASE_URL = st.secrets["SUPABASE_URL"]  # Add this to your secrets.toml
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
GRAPH_URL = "https://graph.facebook.com/v23.0"
CLOUD_NAME = st.secrets["CLOUD_NAME"]
API_KEY = st.secrets["API_KEY"]

#______________________________________________________________________________________________________#

# 🌐 Configure Cloudinary
cloudinary.config(
    cloud_name=CLOUD_NAME,
    api_key=API_KEY,
    api_secret=API_SECRET
)
def upload_to_cloudinary(image_path):
    try:
        result = cloudinary.uploader.upload(image_path)
        url = result.get("secure_url")
        print(f"✅ Uploaded to Cloudinary: {url}")
        return url
    except Exception as e:
        print(f"❌ Cloudinary upload failed: {e}")
        return None
    
#______________________________________________________________________________________________________#

def get_recent_media(limit=5):
    url = f"{GRAPH_URL}/{IG_USER_ID}/media"
    params = {
        "fields": "id,timestamp,caption,media_type,media_url",
        "limit": limit,
        "access_token": ACCESS_TOKEN
    }
    res = requests.get(url, params=params).json()
    return res.get('data', [])

def get_media_engagement(media_id):
    url = f"{GRAPH_URL}/{media_id}/insights"
    params = {
        "metric": "reach,likes,comments,shares,saved,total_interactions",
        "access_token": ACCESS_TOKEN
    }
    res = requests.get(url, params=params).json()
    insights = res.get("data", [])

    if not insights:
        return {}

    return {i['name']: i['values'][0]['value'] for i in insights}

def build_post_insight_json():
    posts = get_recent_media()
    bundle = []

    for post in posts:
        post_data = {
            "id": post["id"],
        }

        # Parse timestamps
        timestamp_utc = parser.isoparse(post["timestamp"])
        timestamp_est = timestamp_utc.astimezone(pytz.timezone("US/Eastern"))
        post_data["timestamp_est"] = timestamp_est.isoformat()

        # Add engagement
        metrics = get_media_engagement(post["id"])
        post_data["metrics"] = metrics

        bundle.append(post_data)

    return bundle

#______________________________________________________________________________________________________#
#Database codes

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def post_already_scheduled(image_name, scheduled_time):
    response = supabase.table("postsdb").select("*").eq("image_path", f"uploads/{image_name}").eq("scheduled_time", str(scheduled_time)).execute()
    return bool(response.data)

def add_post(image_path, caption, scheduled_time, url):
    supabase.table("postsdb").insert({
        "image_path": image_path,
        "caption": caption,
        "scheduled_time": str(scheduled_time),
        "posted": "Pending",
        "image_url": url
    }).execute()

def update_post(post_id, colname, value):
    response = supabase.table("postsdb") \
        .update({f"{colname}": str(value)}) \
        .eq("id", post_id) \
        .execute()
    
    return response

def get_all_posts():
    response = supabase.table("postsdb").select("*").order("scheduled_time", desc=False).execute()
    return response.data if response.data else []

def get_due_posts():
    from datetime import datetime
    now = datetime.now().isoformat()
    response = supabase.table("postsdb").select("*").eq("posted", "Pending").lte("scheduled_time", now).execute()
    return response.data if response.data else []

def mark_posted(post_id):
    supabase.table("postsdb").update({"posted": "Completed"}).eq("id", post_id).execute()

def delete_post(post_id):
    supabase.table("postsdb").delete().eq("id", post_id).execute()
#End of Database codes
#______________________________________________________________________________________________________#

#Generate captions
def generate_caption(image_path, image_name, engagement_data):

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {st.secrets['OPENAI_API_KEY']}"
    }

    with open(image_path, "rb") as img_file:
        image_data = img_file.read()
    base64_image = base64.b64encode(image_data).decode('utf-8')


    # -------------------- Step 1: Recommended Posting Time Prompt --------------------

    recommended_time_prompt = f"""
    You are a social media strategist helping an eyewear brand optimize their Instagram posting schedule.

    Your task is to:
    • Analyze hourly engagement trends across past posts.
    • Optionally factor in follower online activity per hour (if available).
    • Recommend the **single best hour to post (in EST)** to maximize visibility and engagement.

    Data available:
    • Post timestamps (UTC + EST)
    • Engagement metrics per post: likes, comments, shares, saves, total_interactions
    • Average engagement per hour (0–23 UTC)
    • (Optional) Online follower distribution by hour

    Instructions:
    • Prioritize hours where engagement is consistently high.
    • If follower activity supports the same hours, boost confidence in those times.
    • Return only the best hour to post (EST), with a short explanation if needed.

    Engagement Data:
    {engagement_data}
    """

    # -------------------- Step 2: Caption Format Structure --------------------

    structure = """
    1. Hook:  
    • One clever, stylish, and confident sentence  
    • Use tasteful emojis  
    • Must feel culturally aware and modern

    2. Core description (2–3 short punchy sentences):  
    • Describe the eyewear or scene  
    • Highlight craftsmanship, culture, quality, and brand values  
    • Mention design names like “Barbados Edition” if visually identifiable  
    • Reference current seasons or cultural moments if relevant

    3. Caption break: Use a single em dash (—)

    4. Hashtags block (max 15):  
    • Always include: #CIKEyewear #CultureInEveryFrame  
    • Choose from:
        #BlackOwnedEyewear  
        #HandmadeInItaly  
        #LuxuryEyewear  
        #BarbadosEdition  
        #AmericaBlackEdition  
        #StatementSunglasses  
        #BuiltByHand  
        #BoldByDesign  
        #SlowFashion  
        #ArtisanEyewear  
        #IslandStyle  
        #BlackLuxury  
        #CulturalCraftsmanship  
        #FounderLed  
        #SummerStyle
    """

    # -------------------- Step 3: Final Prompt to Send to LLM --------------------

    prompt_use = f"""
    Generate an Instagram caption for a photo of CIK Eyewear sunglasses.

    Brand Overview:
    CIK is a Black-owned, Caribbean-American–founded luxury eyewear brand. Every pair is handmade in Italy using premium materials and cultural storytelling. Designs include symbols like the Barbados Trident or the eagle-beak bridge of the America Black Edition. The brand is bold, confident, heritage-driven, and stylish—representing global Black excellence.

    Instructions:
    • Reference the image name `{image_name}` (without file extension if the name makes sense otherwise ignore it)
    • Write a caption that reflects what’s visible or known about the photo
    • Avoid generic filler text or intros
    • Use no more than 200 characters total
    • Match the format and tone defined below
    • Avoid repeating hashtags
    • Style: confident, inclusive, culturally connected, and founder-led

    Follow this structure exactly:
    {structure}

    Your response must always use "Recommended Time:" to indicate the best time to post (don't use anything else to return the time other than "Recommended Time:").    

    Use the following information to determine it:
    {recommended_time_prompt}
    """

    payload = {
        "model": "gpt-4o",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt_use,
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        }
                    }
                ]
            }
        ],
        "max_tokens": 300
    }

    response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)

    if response.status_code == 200:
        data = response.json()
        content = data['choices'][0]['message']['content']
        return content.strip()
    else:
        print("Error:", response.text)
        return None
    
#End of Generate captions code
#______________________________________________________________________________________________________#


METRICS = [
    "views", "reach", "likes", "comments", "shares",
    "saves", "replies", "accounts_engaged", "total_interactions"
]

# Metrics that support time_series
TIME_SERIES_SUPPORTED = ["reach"]

# Fetch total_value (default)
def fetch_total_value(metric):
    params = {
        "metric": metric,
        "period": "day",
        "metric_type": "total_value",
        "access_token": ACCESS_TOKEN
    }
    r = requests.get(BASE_URL, params=params)
    return r.json()

# Fetch time_series (only for reach)
def fetch_time_series(metric):
    params = {
        "metric": metric,
        "period": "day",
        "metric_type": "time_series",
        "access_token": ACCESS_TOKEN
    }
    r = requests.get(BASE_URL, params=params)
    return r.json()

# Process total or time-series data
def get_metric_data(metric):
    if metric in TIME_SERIES_SUPPORTED:
        res = fetch_time_series(metric)
        if "error" in res or not res.get("data"):
            return None, None, res.get("error", {}).get("message", "No data")
        values = res["data"][0].get("values", [])
        df = pd.DataFrame(values)
        df["end_time"] = pd.to_datetime(df["end_time"])
        df.rename(columns={"value": "Value", "end_time": "Date"}, inplace=True)
        return df, df["Value"].sum(), None
    else:
        res = fetch_total_value(metric)
        if "error" in res or not res.get("data"):
            return None, None, res.get("error", {}).get("message", "No data")
        val = res["data"][0]["total_value"].get("value", 0)
        today = pd.to_datetime("today").normalize()
        df = pd.DataFrame([{"Date": today, "Value": val}])
        return df, val, None
    
#Insights functions
def get_account_insights(IG_USER_ID, access_token):

    url = f"https://graph.facebook.com/v18.0/{IG_USER_ID}/insights"

    # Only metrics that actually work with period=day
    metrics = [
        "reach"  # only one reliably working as of API v18
    ]

    params = {
        "metric": ",".join(metrics),
        "period": "days_28",
        "access_token": access_token
    }

    response = requests.get(url, params=params)
    if response.status_code == 200:
        return response.json().get("data", [])
    else:
        print("❌ Error fetching account insights:", response.status_code, response.text)
        return []
 
def get_ig_business_account_id(page_id, access_token):
    url = f'https://graph.facebook.com/v19.0/{page_id}'
    params = {
        'fields': 'instagram_business_account',
        'access_token': access_token
    }
    response = requests.get(url, params=params)
    data = response.json()
    return data.get('instagram_business_account', {}).get('id')

def get_profile_info(IG_USER_ID, access_token):
    url = f'https://graph.facebook.com/v19.0/{IG_USER_ID}'
    params = {
        'fields': 'username,name,biography,website,profile_picture_url,followers_count,media_count',
        'access_token': access_token
    }
    response = requests.get(url, params=params)
    return response.json()

def get_recent_posts(IG_USER_ID, access_token):
    url = f'https://graph.facebook.com/v19.0/{IG_USER_ID}/media'
    params = {
        'fields': 'id,caption,media_type,media_url,timestamp,like_count,comments_count',
        'access_token': access_token
    }
    response = requests.get(url, params=params)
    return response.json().get('data', [])

def get_post_insights(media_id, access_token):
    url = f'https://graph.facebook.com/v19.0/{media_id}/insights'
    params = {
        'metric': 'impressions,reach,engagement,saved',
        'access_token': access_token
    }
    response = requests.get(url, params=params)
    return response.json().get('data', [])

from PIL import Image

# Re-save uploaded image to ensure format compatibility
def convert_image(input_path, output_format='jpg'):
    if output_format.lower() not in ['jpg', 'png']:
        raise ValueError("Output format must be 'jpg' or 'png'")

    # Register HEIF plugin
    pillow_heif.register_heif_opener()

    image = Image.open(input_path)
    output_path = os.path.splitext(input_path)[0] + f".{output_format}"
    image_format = 'JPEG' if output_format.lower() == 'jpg' else 'PNG'
    image.save(output_path, format=image_format)
    # print(f"Converted: {input_path} → {output_path}")
    return output_path


st.set_page_config(page_title="Instagram Auto Poster")
posting_status = False

# Set up session state for login
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

# Only show Login menu if not logged in
if not st.session_state.logged_in:
    st.sidebar.title("Instagram Auto Poster")
    st.title("🔐 Login to Instagram")
    st.write("Please enter your Instagram credentials to continue.")

    entered_username = st.text_input("Username", type="default")
    entered_password = st.text_input("Password", type="password")

    if st.button("Login"):
        if entered_username and entered_password:
            if entered_username == USERNAME and entered_password == PASSWORD:
                st.success("Login successful! Redirecting to Home page...")
                st.session_state.logged_in = True
                st.rerun()
            else:
                st.error("Invalid username or password.")
        else:
            st.error("Please enter both username and password.")
else:

    menu = st.sidebar.selectbox(
        "Select a page:",
        ["Home", "Configuration", "Analytics", "Detailed Insights", "Scheduled Posts", "Logout"]
    )
    # Display content based on menu selection
    if menu == "Home":
        st.title("📱 Instagram Auto Poster")
        st.write("Welcome to the Home page!")

        st.header("Select schedule criteria")
        num_of_posts = st.number_input("Number of posts per interval", min_value=1, step=1, format="%d")
        frequency = st.selectbox("Post frequency", ["Daily", "Weekly", "Monthly"])
        st.write(f"Number of posts: {num_of_posts}")
        st.write(f"Frequency: {frequency}")
        proceed = False  # Whether to proceed with scheduling

        with st.spinner("Generating engaement data..."):
            engagement_data = build_post_insight_json()     

        if num_of_posts and frequency:
            images = st.file_uploader("Upload Images", type=["jpg", "jpeg", "png", "heic", "heif"], accept_multiple_files=True)
            st.write(f"Number of images uploaded: {len(images) if images else 0}")

            if images and num_of_posts:
           
                total_images = len(images)
                full_batches = total_images // num_of_posts
                remaining_images = total_images % num_of_posts

                # st.info(f"You uploaded **{total_images} images**.")
                st.write(f"That gives you **{full_batches} full batch(es)** of {num_of_posts} images.")

                if remaining_images != 0:
                    st.warning(f"You'll have **{remaining_images} leftover image(s)** which won’t fill a complete batch.")

                    user_choice = st.radio("Do you want to proceed with this?", ["Nothing selected", "Yes, proceed", "No, I'll upload more images"])

                    if user_choice == "Yes, proceed":
                        proceed = True
                    else:
                        st.stop()
                else:
                    proceed = True

                if proceed:
                    # Generate the schedule
                    interval_days = {"daily": 1, "weekly": 7, "monthly": 30}[frequency.lower()]
                    start_date = datetime.today().date()
                    index = 0

                    image_schedule = []
                    for batch_num in range(full_batches + (1 if remaining_images else 0)):
                        batch_images = images[index: index + num_of_posts]
                        index += num_of_posts
                        post_date = start_date + timedelta(days=batch_num * interval_days)
                        for img in batch_images:
                            image_schedule.append((post_date, img))

                    if st.checkbox("Show posting schedule"):
                        # Show schedule
                        st.success("✅ Your posts will be scheduled as follows:")

                        for scheduled_date, img_file in image_schedule:
                            if isinstance(scheduled_date, str):
                                scheduled_date = datetime.strptime(scheduled_date, "%Y-%m-%d")

                            st.markdown(f"**{scheduled_date.strftime('%Y-%m-%d')}**")
                            cols = st.columns(5)
                            try:
                                img = Image.open(img_file)
                                img.thumbnail((150, 150))
                                with cols[0]:
                                    st.image(img, caption=img_file.name, use_container_width=True)
                            except Exception as e:
                                st.warning(f"Could not display image: {e}")

        else:
            st.warning("Please enter the number of posts and select a frequency before uploading images.")
            images = None
        caption = ""
        converted_image_path = None
        if images:
            for post_date, image in image_schedule:
                try:
                    # Step 1: Save uploaded image temporarily
                    temp_input_path = os.path.join("temp", image.name)
                    os.makedirs("temp", exist_ok=True)
                    with open(temp_input_path, "wb") as f:
                        f.write(image.getbuffer())

                    # Step 2: Convert image and save to uploads
                    os.makedirs("uploads", exist_ok=True)
                    converted_image_path = convert_image(temp_input_path, "jpg")
                    final_image_path = os.path.join("uploads", os.path.basename(converted_image_path))
                    if os.path.exists(final_image_path):
                        os.remove(final_image_path)
                    os.rename(converted_image_path, final_image_path)

                    # Step 3: Upload to Cloudinary
                    url = upload_to_cloudinary(final_image_path)
                    if not url:
                        st.error(f"❌ Failed to upload image: {image.name}")
                        continue
                    st.success(f"✅ Image uploaded: {image.name}")

                    # Step 4: Generate caption if not cached
                    if (
                        "generated_caption" not in st.session_state
                        or st.session_state.get("last_image") != image.name
                    ):
                        with st.spinner("Generating caption..."):
                            st.session_state.generated_caption = generate_caption(final_image_path, image.name, engagement_data)
                            st.session_state.last_image = image.name

                    generated_output = st.session_state.generated_caption
                    caption = generated_output.split("Recommended Time:")[0].strip()

                    # Step 5: Extract time (e.g. "6 PM")
                    hour = 12  # Default
                    match = re.search(r"(\d{1,2})\s*(AM|PM)", generated_output, re.IGNORECASE)
                    if match:
                        hour = int(match.group(1))
                        period = match.group(2).upper()
                        if period == "PM" and hour != 12:
                            hour += 12
                        elif period == "AM" and hour == 12:
                            hour = 0
                    else:
                        st.warning("⚠️ Recommended time not found, using 12:00 PM default")

                    # Step 6: Schedule post
                    if posting_status is False:
                        selected_time = datetime.combine(post_date, datetime.min.time()).replace(hour=hour, minute=0)
                        if post_already_scheduled(image.name, selected_time):
                            st.info(f"✅ Already scheduled: {image.name} on {selected_time}")
                        else:
                            add_post(final_image_path, caption, selected_time, url)
                            st.success(f"✅ Post scheduled successfully for {image.name}")
                    else:
                        st.info("Post already scheduled.")

                except Exception as e:
                    st.error(f"❌ Error processing image {image.name}: {e}")


    elif menu == "Analytics":
        st.title("📊 Analytics Dashboard")
        tab1, tab2 = st.tabs(["📄 Profile Info", "📸 Recent Posts"])

        with tab1:
            profile = get_profile_info(IG_USER_ID, ACCESS_TOKEN)

            st.subheader(f"Username: {profile.get('username')}")
            st.write(f"**Name:** {profile.get('name')}")
            st.write(f"**Biography:** {profile.get('biography')}")
            st.write(f"**Website:** {profile.get('website')}")
            st.image(profile.get('profile_picture_url'), width=150)
            st.write(f"**Followers Count:** {profile.get('followers_count')}")
            st.write(f"**Total Media Posts:** {profile.get('media_count')}")

        with tab2:
            posts = get_recent_posts(IG_USER_ID, ACCESS_TOKEN)

            for i in range(0, len(posts), 3):
                cols = st.columns(3)
                for j in range(3):
                    if i + j < len(posts):
                        post = posts[i + j]
                        with cols[j]:
                            st.markdown("---")
                            st.write(f"**Post ID:** {post['id']}")
                            # st.write(f"**Caption:** {post.get('caption', 'N/A')}")
                            st.write(f"**Media Type:** {post['media_type']}")
                            if post['media_type'] == "IMAGE":
                                st.image(post['media_url'], width=300)
                            elif post['media_type'] == "VIDEO":
                                st.video(post['media_url'])
                            elif post['media_type'] == "CAROUSEL_ALBUM":
                                st.write("Carousel post. [View Media]({})".format(post['media_url']))
                            else:
                                st.write(f"Media URL: {post['media_url']}")
                            # st.write(f"**Timestamp:** {post['timestamp']}")
                            ts = post['timestamp']
                            
                            try:
                                # Fix timezone format for fromisoformat
                                ts_fixed = ts.replace("+0000", "+00:00")
                                dt = datetime.fromisoformat(ts_fixed)
                                st.write(f"**Date:** {dt.date()} | **Time:** {dt.strftime('%H:%M:%S')}")
                            except Exception:
                                st.write(f"**Timestamp:** {ts}")                       
                            st.write(f"**Like Count:** {post.get('like_count', 'N/A')}")
                            st.write(f"**Comments Count:** {post.get('comments_count', 'N/A')}")

    elif menu == "Detailed Insights":
        #Prod
        import streamlit as st
        import requests
        import pandas as pd
        import plotly.express as px
        import json
        import os

        # Metrics we want to show
        METRICS = [
            "views", "reach", "likes", "comments", "shares",
            "saves", "replies", "accounts_engaged", "total_interactions"
        ]

        # Metrics that support time_series
        TIME_SERIES_SUPPORTED = ["reach"]

        # Fetch total_value (default)
        def fetch_total_value(metric):
            params = {
                "metric": metric,
                "period": "day",
                "metric_type": "total_value",
                "access_token": ACCESS_TOKEN
            }
            r = requests.get(BASE_URL, params=params)
            return r.json()

        def fetch_total_value_lifetime(metric):
            params = {
                "metric": metric,
                "period": "day",  # or "day", "days_28"
                "metric_type": "total_value",
                "access_token": ACCESS_TOKEN
            }
            r = requests.get(BASE_URL, params=params)
            return r.json()

        # Fetch time_series (only for reach)
        def fetch_time_series(metric):
            params = {
                "metric": metric,
                "period": "day",  # or "day", "week"
                "metric_type": "time_series",
                "access_token": ACCESS_TOKEN
            }
            r = requests.get(BASE_URL, params=params)
            return r.json()

        # Process total or time-series data
        def get_metric_data(metric):
            if metric in TIME_SERIES_SUPPORTED:
                res = fetch_time_series(metric)
                if "error" in res or not res.get("data"):
                    return None, None, res.get("error", {}).get("message", "No data")
                values = res["data"][0].get("values", [])
                df = pd.DataFrame(values)
                df["end_time"] = pd.to_datetime(df["end_time"])
                df.rename(columns={"value": "Value", "end_time": "Date"}, inplace=True)
                return df, df["Value"].sum(), None
            else:
                res = fetch_total_value(metric)
                if "error" in res or not res.get("data"):
                    return None, None, res.get("error", {}).get("message", "No data")
                val = res["data"][0]["total_value"].get("value", 0)
                today = pd.to_datetime("today").normalize()
                df = pd.DataFrame([{"Date": today, "Value": val}])
                return df, val, None

        def get_aggregated_metric(metric):
            url = f"https://graph.facebook.com/{API_VERSION}/{IG_USER_ID}/media"
            params = {
                "fields": f"{metric}",
                "access_token": ACCESS_TOKEN,
                "limit": 100  # adjust as needed
            }
            r = requests.get(url, params=params)
            data = r.json().get("data", [])
            return sum(item.get(metric, 0) for item in data)


        st.title("📊 Instagram Insights Dashboard")

        tab1, tab2 = st.tabs(["📋 Table View", "📈 Charts View"])

        # --- TAB 1: TABLE VIEW ---
        with tab1:
            METRIC_FIELD_MAP = {
                "likes": "like_count",
                "comments": "comments_count",
                # "shares": "shares_count",  # Only if available
            }    
            st.subheader("📋 Summary Table")
            rows = []
            # List of metrics to aggregate from media
            AGGREGATE_FROM_MEDIA = list(METRIC_FIELD_MAP.keys())

            for metric in METRICS:
                if metric in AGGREGATE_FROM_MEDIA:
                    field = METRIC_FIELD_MAP[metric]
                    val = get_aggregated_metric(field)
                    err = None
                else:
                    _, val, err = get_metric_data(metric)
                rows.append({
                    "Metric": metric.replace("_", " ").title(),
                    "Value": val if val is not None else f"⚠️ {err}"
                })
            st.table(pd.DataFrame(rows))

            with tab2:
                st.subheader("📈 Metric Visualizations")

                # Each row contains 3 charts
                col_index = 0
                chart_cols = st.columns(2)

                # Define a funnel order if you want to show a funnel
                FUNNEL_METRICS = ["reach", "accounts_engaged", "total_interactions"]

                # Prepare funnel data
                funnel_data = []
                for metric in FUNNEL_METRICS:
                    _, val, err = get_metric_data(metric)
                    funnel_data.append({"Metric": metric.replace("_", " ").title(), "Value": val if val is not None else 0})

                for idx, metric in enumerate(METRICS):
                    col = chart_cols[col_index]
                    with col:
                        st.markdown(f"#### {metric.replace('_', ' ').title()}")

                        # Area chart for time series
                        if metric in TIME_SERIES_SUPPORTED:
                            df_ts, _, err = get_metric_data(metric)
                            if err:
                                st.warning(f"{metric}: {err}")
                            elif df_ts is not None:
                                # Convert to date only and group by date (in case there are multiple times per day)
                                df_ts["Date"] = pd.to_datetime(df_ts["Date"]).dt.date
                                df_ts = df_ts.groupby("Date", as_index=False)["Value"].sum()
                                # Sort by date ascending
                                df_ts = df_ts.sort_values("Date", ascending=True)
                                st.write(df_ts)  # Add this line to inspect your data
                                fig = px.bar(df_ts, x="Date", y="Value", title=metric.replace("_", " ").title())
                                st.plotly_chart(fig, use_container_width=True)

                        # Funnel chart for the funnel metrics (only show once)
                        elif metric == FUNNEL_METRICS[0]:
                            df_funnel = pd.DataFrame(funnel_data)
                            fig = px.funnel(df_funnel, x="Value", y="Metric", title="Funnel: Reach → Engaged → Interactions")
                            st.plotly_chart(fig, use_container_width=True)
                        else:
                            if metric in AGGREGATE_FROM_MEDIA:
                                field = METRIC_FIELD_MAP[metric]
                                total = get_aggregated_metric(field)
                                df = pd.DataFrame([{"Metric": metric.replace("_", " ").title(), "Value": total}])
                                fig = px.bar(df, x="Metric", y="Value", title=f"{metric.replace('_', ' ').title()} (Aggregated)")
                                st.plotly_chart(fig, use_container_width=True)
                            else:
                                # Try breakdowns for donut chart
                                res = fetch_total_value(metric)

                                if "error" in res or not res.get("data"):
                                    st.warning(f"{metric}: {res.get('error', {}).get('message', 'No data')}")
                                else:
                                    item = res["data"][0]
                                    breakdowns = item["total_value"].get("breakdowns", [])
                                    if breakdowns:
                                        breakdown_data = []
                                        for br in breakdowns:
                                            for r in br["results"]:
                                                dims = " | ".join(r["dimension_values"])
                                                breakdown_data.append({"Category": dims, "Value": r["value"]})
                                        df = pd.DataFrame(breakdown_data)
                                        if not df.empty:
                                            fig = px.pie(df, names="Category", values="Value", hole=0.4)
                                            st.plotly_chart(fig, use_container_width=True)
                                        else:
                                            st.info("No breakdown data available.")
                                    else:
                                        # Just show total as bar
                                        total = item["total_value"].get("value", 0)
                                        df = pd.DataFrame([{"Metric": metric, "Value": total}])
                                        fig = px.bar(df, x="Metric", y="Value")
                                        st.plotly_chart(fig, use_container_width=True)

                    col_index = (col_index + 1) % 2
                    if col_index == 0 and idx != len(METRICS) - 1:
                        chart_cols = st.columns(2)
        st.markdown("----")

    elif menu == "Scheduled Posts":
        st.title("📅 Scheduled Posts Calendar View")
        tab1, tab2 = st.tabs(["📅 Calendar View", "📝 Manage Scheduled Posts"])
        with tab1:
            posts = get_all_posts()
            # print("Fetched posts", posts)

            if posts:
                # Transform posts into calendar events
                calendar_events = []
                for post in posts:
                    # Create a hover-friendly string with ID, status, caption
                    hover_text = (
                        f"ID: {post['id']}\n"
                        f"Status: {post['posted']}\n"
                        
                        # f"Caption: {post.get('caption', 'No caption')}"
                    )
                    
                    calendar_events.append({
                        "title": hover_text,  # This will show on hover
                        "start": post['scheduled_time'],
                        "color": "#28a745" if post["posted"] else "#ffc107",
                    })
                
                options = {
                    "initialView": "dayGridMonth",
                    "editable": False,
                    "selectable": False,
                    "height": 650,
                    "headerToolbar": {
                        "left": "prev,next today",
                        "center": "title",
                        "right": "dayGridMonth,timeGridWeek,timeGridDay"
                    },
                    "eventTimeFormat": {
                        "hour": "numeric",
                        "minute": "2-digit",
                        "meridiem": "short",
                        "hour12": True
                    }
                }

                calendar(events=calendar_events, options=options)

            else:
                st.info("No scheduled posts found.")

            with tab2:
                st.subheader("Manage Scheduled Posts")
                posts = sorted(posts, key=lambda x: x['id'], reverse=True)

                for post in posts:
                    with st.expander(f"📌 Post ID {post['id']}", expanded=False):
                        action_col1, action_col2, action_col3 = st.columns([6, 2, 2])
                        with action_col1:
                            st.write(
                                f"**ID:** {post['id']} | "
                                f"**Time:** {post['scheduled_time']} | "
                                f"**Status:** {post['posted']} |"
                            )

                        with action_col2:
                            if st.button("Delete", key=f"delete_{post['id']}"):
                                delete_post(post['id'])
                                st.success(f"Deleted post ID {post['id']}")
                                st.rerun()

                        with action_col3:
                            edit_date = st.checkbox("✏️ Edit Date", key=f"edit_date_toggle_{post['id']}")

                        if edit_date:
                            post_dt = (
                                datetime.fromisoformat(post['scheduled_time'])
                                if isinstance(post['scheduled_time'], str)
                                else post['scheduled_time']
                            )
                            new_date = st.date_input(f"Date", value=post_dt.date())
                            new_time = st.time_input(f"Time", value=post_dt.time())
                            new_datetime = datetime.combine(new_date, new_time)

                            if new_datetime != post_dt:
                                if st.button("Save New Time", key=f"save_{post['id']}"):
                                    update_post(post['id'], 'scheduled_time', new_datetime)
                                    st.success(f"Updated post ID {post['id']} to {new_datetime}")
                                    time.sleep(1)
                                    st.rerun()

                        # Layout for caption and image
                        left_col, right_col = st.columns([3, 1])

                        with left_col:
                            if post.get("caption"):
                                default_caption = post.get("caption", "")
                                new_caption = st.text_area(
                                    "Edit Caption",
                                    value=default_caption,
                                    key=f"caption_input_{post['id']}",
                                    height=150,
                                )

                                if new_caption != default_caption:
                                    if st.button("Update Caption", key=f"update_caption_{post['id']}"):
                                        update_post(post['id'], 'caption', new_caption)
                                        st.success("Caption updated successfully.")
                                        time.sleep(1)
                                        st.rerun()

                        with right_col:
                            if post.get("image_url"):
                                st.image(post["image_url"], width=150, caption="Preview")

    elif menu == "Configuration":
        st.warning("This feature is under development. Please check back later.")
    #     DEFAULT_CONFIG_KEYS = [
    #     "ACCESS_TOKEN", "IG_USER_ID"
    # ]
    #     st.title("🔧 Configuration")
    #     st.write("Configure your Instagram API settings here.")

        # for key in DEFAULT_CONFIG_KEYS:
        #     config[key] = st.text_input(
        #         f"Enter {key.replace('_', ' ').title()}:",
        #         value=config.get(key, ""),
        #         type="password" if "TOKEN" in key or "SECRET" in key or "KEY" in key else "default"
        #     )

        # if st.button("Save Configuration"):
        #     save_config(config)
        #     st.success("Configuration saved! Please reload the app.")
        #     st.stop()

    elif menu == "Logout":
        st.session_state.logged_in = False
        st.success("You have been logged out successfully.")
        st.rerun()
