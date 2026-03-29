import requests
from io import BytesIO
from PIL import Image

def get_latest_radar(radar_id):
    import re
    # We can get the latest from ftp via listing, but an easier way is https BOM
    # The BOM product page actually contains the latest image URL, or we can use the JSON product feed
    # Or just hit ftp via requests? requests doesn't support FTP natively!
    return None

import urllib.request
def fetch_radar():
    pass
