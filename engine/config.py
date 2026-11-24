"""Every setting the engine uses, in one place.

Change the size bands here. Each band's shape covers everything at or above its
lower edge, so the shapes stack (the 1.5" shape sits inside the 1" shape, and so on).
"""

from datetime import date

# Bump when the file formats change in a way readers must know about.
DATA_VERSION = 1

# Lower edges of the size bands, in inches. The last band has no upper edge.
BANDS = [1.0, 1.5, 2.0, 2.5]
MIN_INCHES = BANDS[0]

# Storm season: every day from April 1 to October 31 is processed. Days outside it
# are processed only when there is a ground hail report in Colorado that day.
SEASON_START = (4, 1)
SEASON_END = (10, 31)

TIMEZONE = "America/Denver"

# Colorado, as the box the website's map uses (degrees). Colorado's borders are lines
# of latitude and longitude, so the box is the state.
WEST, EAST, NORTH, SOUTH = -109.06, -102.04, 41.0, 36.99

# The NOAA MRMS grid (checked against every file read; the engine stops if it changes).
GRID_FIRST_LAT = 54.995  # centre of the top row
GRID_FIRST_LON = -129.995  # centre of the left column
GRID_STEP = 0.01
GRID_NI = 7000  # columns
GRID_NJ = 3500  # rows

# Shapes: smoothing, smallest spot kept, and rounding of coordinates.
UPSAMPLE = 4  # radar squares are split 4 x 4 and blended, so edges fall between square centres
SIMPLIFY_DEGREES = 0.0015  # about 150 m: removes the small steps left by the split
SMOOTH_PASSES = 3  # corner-rounding passes, for smooth round edges
CURVE_TOLERANCE = 0.0003  # about 30 m: drops extra points along the rounded curves
MIN_AREA_KM2 = 3.0  # radar spots (and holes) smaller than this are dropped as noise
COORD_DECIMALS = 4  # about 10 m, so curves stay smooth when zoomed in

# A city "had radar hail" when radar showed MIN_INCHES or more within this distance of
# its centre.
CITY_RADIUS_MILES = 3.0

# The 22 cities on the website (slug, name, latitude, longitude), from
# content/service-areas.ts in alliance-restoration-website.
CITIES = [
    ("frederick", "Frederick", 40.0992, -104.9372),
    ("firestone", "Firestone", 40.1125, -104.9366),
    ("dacono", "Dacono", 40.0847, -104.9394),
    ("longmont", "Longmont", 40.1672, -105.1019),
    ("boulder", "Boulder", 40.015, -105.2705),
    ("denver", "Denver", 39.7392, -104.9903),
    ("aurora", "Aurora", 39.7294, -104.8319),
    ("lakewood", "Lakewood", 39.7047, -105.0814),
    ("arvada", "Arvada", 39.8028, -105.0875),
    ("westminster", "Westminster", 39.8367, -105.0372),
    ("thornton", "Thornton", 39.868, -104.9719),
    ("broomfield", "Broomfield", 39.9205, -105.0867),
    ("fort-collins", "Fort Collins", 40.5853, -105.0844),
    ("loveland", "Loveland", 40.3978, -105.0749),
    ("greeley", "Greeley", 40.4233, -104.7091),
    ("colorado-springs", "Colorado Springs", 38.8339, -104.8214),
    ("pueblo", "Pueblo", 38.2544, -104.6091),
    ("grand-junction", "Grand Junction", 39.0639, -108.5506),
    ("berthoud", "Berthoud", 40.3083, -105.0811),
    ("centennial", "Centennial", 39.5807, -104.8772),
    ("castle-rock", "Castle Rock", 39.3722, -104.8561),
    ("strasburg", "Strasburg", 39.7383, -104.3233),
]

# Where the radar files come from (free, no key). The archive first, then NOAA's own
# server, which keeps only about the last day.
ARCHIVE_URL = "https://mtarchive.geol.iastate.edu/{t:%Y/%m/%d}/mrms/ncep/{product}/{product}_00.50_{t:%Y%m%d-%H%M%S}.grib2.gz"
REALTIME_URL = "https://mrms.ncep.noaa.gov/2D/{product}/MRMS_{product}_00.50_{t:%Y%m%d-%H%M%S}.grib2.gz"
DAY_PRODUCT = "MESH_Max_1440min"  # 24-hour maximum, one file every 30 minutes
SNAPSHOT_PRODUCT = "MESH"  # every 2 minutes; used only for the odd hour on clock-change days

# Ground reports (NWS Local Storm Reports via the Iowa Environmental Mesonet).
LSR_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/gis/lsr.py"

# Daily run: re-check this many finished days, and retry "missing" days up to this old.
RECHECK_DAYS = 3
RETRY_MISSING_DAYS = 30

USER_AGENT = "alliance-hail-data/1 (radar hail paths for Colorado)"

# ---------------------------------------------------------------- wind

# Wind paths: the strongest gust of each Colorado day from NOAA's hourly wind analysis
# (URMA, 2.5 km), plus the wind gusts and damage the Weather Service received that day.
# Processed every day of the year (Colorado's worst windstorms come in winter).
WIND_DATA_VERSION = 1
WIND_BANDS = [60.0, 70.0, 80.0, 90.0]  # mph, lower edges; the last band has no upper edge
WIND_STEP = 0.02  # the gusts are put on a 0.02-degree Colorado grid (about 2 km)
WIND_UPSAMPLE = 4
WIND_SIMPLIFY_DEGREES = 0.004  # about 400 m; the source squares are 2.5 km
WIND_SMOOTH_PASSES = 3
WIND_CURVE_TOLERANCE = 0.0008
WIND_MIN_AREA_KM2 = 15.0  # a few source squares; smaller spots are noise
WIND_URL = "https://noaa-urma-pds.s3.amazonaws.com/urma2p5.{t:%Y%m%d}/urma2p5.t{t:%H}z.2dvaranl_ndfd.grb2_wexp"
WIND_MAX_MISSING_HOURS = 2  # more missing hours than this and the day is "missing"
# History: the daily run fills in days since this date that aren't done yet, newest
# first, this many per run (the same start as the hail history).
WIND_HISTORY_START = date(2024, 11, 18)
WIND_CATCHUP_DAYS = 400
# Reports kept: gusts at or above this, and every wind-damage report.
WIND_REPORT_MIN_MPH = 50
WIND_REPORT_TYPES = {
    "TSTM WND GST": "gust",
    "NON-TSTM WND GST": "gust",
    "HIGH SUST WINDS": "gust",
    "TSTM WND DMG": "damage",
    "NON-TSTM WND DMG": "damage",
}
