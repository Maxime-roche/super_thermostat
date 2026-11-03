"""Constantes de Super Thermostat."""
from __future__ import annotations

DOMAIN = "super_thermostat"
STORAGE_VERSION = 1

CONF_TYPE = "entry_type"
TYPE_ZONE = "zone"
TYPE_BOILER = "boiler"
TYPE_FRACTION = "fraction"
TYPE_AC = "ac"

# --- zone ---
CONF_NAME = "name"
CONF_TEMP_ENTITY = "temperature_entity"
CONF_OUTDOOR_ENTITY = "outdoor_entity"
CONF_ALLOWED = "allowed_modes"
CONF_CYCLE = "cycle_minutes"
CONF_MAX_SENSOR_AGE = "max_sensor_age"
CONF_FAILSAFE_POWER = "failsafe_power"
CONF_MIN_POWER = "min_power"
CONF_LIMIT_CYCLES = "limit_cycles"
CONF_AUTOLEARN = "autolearn"
CONF_FAIL_OFFSET_HEAT = "fail_offset_heat"
CONF_FAIL_OFFSET_COOL = "fail_offset_cool"
CONF_THRESHOLD_HOT = "threshold_hot"
CONF_OFFSET_NEXT_FULL = "offset_next_full"
CONF_DIR_DELTA_HEAT = "dir_delta_heat"
CONF_DIR_DELTA_COOL = "dir_delta_cool"
CONF_FRACTION_ENTITY = "boiler_fraction_entity"
CONF_ZONE_SEASON = "season_entity"
FIXED_PRESETS = "home, sleep, away"  # Jour, Nuit, Parti : fixes
CONF_VALVES = "valve_entities"
CONF_VALVE_MODE = "valve_mode"
CONF_VALVE_LEVEL = "valve_open_level"
CONF_VALVE_CUSTOM = "valve_custom_entity"
CONF_WINDOWS = "windows"
CONF_WINDOW_STOP_DELAY = "window_stop_delay"
CONF_WINDOW_RESTART_DELAY = "window_restart_delay"

ALLOWED_HEAT = "heat"
ALLOWED_COOL = "cool"
ALLOWED_ALL = "all"

CONF_VALVE_POSITIONS = "valve_position_entities"  # position réelle de chaque vanne (même ordre que les vannes)
CONF_VALVE_ALERT_MINUTES = "valve_alert_minutes"    # 0 = alerte désactivée
VALVE_ALERT_GAP = 10  # écart fixe (%) entre consigne et position réelle avant de compter une dérive
CONF_VALVE_SOURCE = "valve_source"            # entité 0-100 % qui pilote l'ouverture (vide = puissance chaudière de la zone)
CONF_VALVE_NEVER_CLOSE = "valve_never_close"  # ne jamais fermer complètement : minimum d'ouverture
CONF_VALVE_FOLLOW = "valve_follow"
CONF_VALVE_OPEN_MIN = "valve_open_min"
CONF_VALVE_OPEN_MAX = "valve_open_max"
CONF_VALVE_MIN_STEP = "valve_min_step"
CONF_VALVE_KEEP_OPEN = "valve_keep_open"
VALVE_DEMAND = "demand"            # ancien mode « ouvert / fermé » (traité comme proportionnel min = max)
VALVE_PROPORTIONAL = "proportional"  # ouverture proportionnelle à la demande de la zone
VALVE_FRACTION = "fraction"        # ouverture = fraction chaudière
VALVE_CUSTOM = "custom"            # ouverture = valeur d'une entité choisie
FOLLOW_BOILER = "boiler"           # demande suivie : puissance chaudière de la zone
FOLLOW_TOTAL = "total"             # demande suivie : puissance de chauffe totale

DEFAULT_ZONE_OPTIONS = {
    CONF_CYCLE: 60,
    CONF_MAX_SENSOR_AGE: 120,
    CONF_FAILSAFE_POWER: 0,
    CONF_MIN_POWER: 5,
    CONF_LIMIT_CYCLES: False,
    CONF_AUTOLEARN: True,
    CONF_FAIL_OFFSET_HEAT: 1,
    CONF_FAIL_OFFSET_COOL: 1,
    CONF_THRESHOLD_HOT: 100,
    CONF_OFFSET_NEXT_FULL: 0,
    CONF_DIR_DELTA_HEAT: 0,
    CONF_DIR_DELTA_COOL: 0,
    CONF_VALVE_LEVEL: 100,  # ancien mode « demande »
    CONF_VALVE_FOLLOW: FOLLOW_BOILER,
    CONF_VALVE_OPEN_MIN: 15,
    CONF_VALVE_OPEN_MAX: 70,
    CONF_VALVE_MIN_STEP: 5,
    CONF_VALVE_KEEP_OPEN: True,
    CONF_VALVE_NEVER_CLOSE: False,
    CONF_VALVE_ALERT_MINUTES: 30,
    CONF_WINDOW_STOP_DELAY: 2,
    CONF_WINDOW_RESTART_DELAY: 2,
}

# statuts de zone
Z_HEATING = "heating"
Z_COOLING = "cooling"
Z_IDLE = "idle"
Z_OFF = "off"
Z_SUSPENDED = "suspended"
Z_SENSOR_FAILURE = "sensor_failure"
Z_ACTUATOR_FAILURE = "actuator_failure"
ZONE_STATUSES = [
    Z_HEATING, Z_COOLING, Z_IDLE, Z_OFF, Z_SUSPENDED,
    Z_SENSOR_FAILURE, Z_ACTUATOR_FAILURE,
]

DEFAULT_TARGET_HEAT = 20.0
DEFAULT_TARGET_COOL = 24.0
COOL_OFF = 35.0  # consigne de froid >= 35 °C = « clim coupée »
MIN_TEMP = 5.0
MAX_TEMP = 35.0
# consignes (chauffe, froid) proposées ; sinon 20 / 24
PRESET_DEFAULTS = {
    "home": (21.0, 24.0), "comfort": (21.0, 24.0), "eco": (19.0, 26.0),
    "sleep": (19.0, COOL_OFF), "away": (18.0, COOL_OFF), "boost": (22.0, 24.0),
    "activity": (20.0, 24.0), "soiree": (20.0, 24.0), "vacances": (14.0, COOL_OFF),
}
# noms standards de Home Assistant : ils donnent les icônes de la tuile « préréglages »
STANDARD_PRESETS = ("home", "comfort", "eco", "sleep", "away", "boost", "activity")
PRESET_ALIASES = {
    "jour": "home", "maison": "home", "confort": "comfort", "nuit": "sleep",
    "sommeil": "sleep", "parti": "away", "absent": "away", "absence": "away",
}
PRESET_LABELS = {
    "home": "Jour", "comfort": "Confort", "eco": "Éco", "sleep": "Nuit",
    "away": "Parti", "boost": "Boost", "activity": "Activité",
}

# --- chaudière ---
CONF_BURNER = "burner_entity"
CONF_CIRCULATOR = "circulator_entity"
CONF_WATER_TEMP = "water_temperature_entity"
CONF_SOURCES = "power_sources"
CONF_COOL_SOURCES = "cool_sources"
CONF_POST_RUN = "post_run_minutes"
CONF_MIN_ON = "min_on_minutes"
CONF_MIN_OFF = "min_off_minutes"
CONF_SAFETY_MAX = "safety_max"
CONF_WATER_MAX_AGE = "water_max_age"

DEFAULT_BOILER_OPTIONS = {
    CONF_POST_RUN: 0,
    CONF_MIN_ON: 2,
    CONF_MIN_OFF: 2,
    CONF_SAFETY_MAX: 85,
    CONF_WATER_MAX_AGE: 10,
}
DEFAULT_T_MIN = 20.0
DEFAULT_T_MAX = 72.0
DEFAULT_OFFSET = 5.0

B_DISABLED = "disabled"
B_IDLE = "idle"
B_CIRCULATING = "circulating"
B_HEATING = "heating"
B_WATER_FAILURE = "water_sensor_failure"
B_SAFETY = "safety_cutoff"
BOILER_STATUSES = [B_DISABLED, B_IDLE, B_CIRCULATING, B_HEATING, B_WATER_FAILURE, B_SAFETY]

# --- fraction chaudière (répartition chaudière / clim) ---
CONF_FRACTION_SOURCE = "source_entity"
CONF_FRACTION_MODE = "source_mode"
CONF_FALLBACK_TEMP = "fallback_temperature"
MODE_VALUE = "value"
MODE_YESTERDAY = "yesterday_mean"
CONF_SEUIL_HAUT = "seuil_haut"
CONF_SEUIL_BAS = "seuil_bas"
CONF_MIN_FRACTION = "min_fraction"
DEFAULT_FRACTION_OPTIONS = {
    CONF_FRACTION_MODE: MODE_YESTERDAY, CONF_FALLBACK_TEMP: 10,
    CONF_SEUIL_HAUT: 9, CONF_SEUIL_BAS: -3, CONF_MIN_FRACTION: 15,
}

# --- gestion clim ---
CONF_CLIMATE = "climate_entity"
CONF_AC_FRACTION = "fraction_entity"
CONF_SUMMER = "summer_entity"
CONF_START_DELAY = "start_delay"
CONF_ADJUST_INTERVAL = "adjust_interval"
CONF_AC_MIN_ON = "ac_min_on"
CONF_MODE_DELAY = "mode_delay"
DEFAULT_AC_OPTIONS = {
    CONF_START_DELAY: 10, CONF_ADJUST_INTERVAL: 5, CONF_AC_MIN_ON: 5, CONF_MODE_DELAY: 20,
}
A_DISABLED = "disabled"
A_IDLE = "idle"
A_HEATING = "heating"
A_COOLING = "cooling"
A_FRACTION_CUTOFF = "fraction_cutoff"
A_SUMMER = "summer_season"
AC_STATUSES = [A_DISABLED, A_IDLE, A_HEATING, A_COOLING, A_FRACTION_CUTOFF, A_SUMMER]
