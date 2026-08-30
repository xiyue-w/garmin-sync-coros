import os
import sys
from datetime import datetime
import logging
import time
import warnings

CURRENT_DIR = os.path.split(os.path.abspath(__file__))[0]  # 当前目录
config_path = CURRENT_DIR.rsplit('/', 1)[0]  # 上三级目录
sys.path.append(config_path)

def configure_optional_telemetry():
    enable_logfire = str(os.getenv("ENABLE_LOGFIRE", "0")).lower() in ("1", "true", "yes", "on")
    if enable_logfire:
        return

    os.environ.setdefault("OTEL_SDK_DISABLED", "true")
    os.environ.setdefault("LOGFIRE_IGNORE_NO_CONFIG", "1")
    warnings.filterwarnings(
        "ignore",
        message=r"Logfire API returned status code .*",
        category=UserWarning,
    )

from config import DB_DIR, GARMIN_FIT_DIR, resolve_sync_config
from garmin.garmin_client import GarminClient
from garmin.garmin_db import GarminDB
from coros.coros_client import CorosClient
from oss.ali_oss_client import AliOssClient
from oss.aws_oss_client import AwsOssClient
from utils.md5_utils import calculate_md5_file

configure_optional_telemetry()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

if str(os.getenv("ENABLE_LOGFIRE", "0")).lower() not in ("1", "true", "yes", "on"):
    for logger_name in ("logfire", "opentelemetry", "opentelemetry.sdk"):
        logging.getLogger(logger_name).setLevel(logging.CRITICAL)

SYNC_CONFIG = {
    'GARMIN_AUTH_DOMAIN': '',
    'GARMIN_EMAIL': '',
    'GARMIN_PASSWORD': '',
    'GARMIN_NEWEST_NUM': 10000,
    "COROS_EMAIL": '',
    "COROS_PASSWORD": '',
}

def get_activity_name(activity, garmin_client):
    activity_name = activity.get("activityName")
    if activity_name:
        return activity_name

    try:
        activity_summary = garmin_client.getActivity(activity["activityId"])
    except Exception as err:
        logging.warning(
            "Failed to load Garmin detail for activity %s metadata: %s",
            activity["activityId"],
            err,
        )
        return activity_name

    return activity_summary.get("activityName") or activity_name

def init(coros_db):
    ## 判断RQ数据库是否存在
    print(os.path.join(DB_DIR, coros_db.garmin_db_name))
    if not os.path.exists(os.path.join(DB_DIR, coros_db.garmin_db_name)):
        ## 初始化建表
        coros_db.initDB()
    coros_db.ensureColumns()
    if not os.path.exists(GARMIN_FIT_DIR):
        os.mkdir(GARMIN_FIT_DIR)

def safe_get_all(client, retries=5):
    last_error = None
    for i in range(retries):
        try:
            return client.getAllActivities()
        except Exception as e:
            last_error = e
            if "refusing to retry immediately" in str(e):
                break
            wait = min(60, 2 ** i)
            print(f"getAllActivities failed ({e}), retrying in {wait}s...")
            time.sleep(wait)
    raise RuntimeError("Failed to fetch activities after retries.") from last_error

if __name__ == "__main__":

  SYNC_CONFIG = resolve_sync_config(SYNC_CONFIG)
  
  ## db 名称
  db_name = "garmin.db"
  ## 建立DB链接
  garmin_db = GarminDB(db_name)
  ## 初始化DB位置和下载文件位置
  init(garmin_db)

  GARMIN_EMAIL = SYNC_CONFIG["GARMIN_EMAIL"]
  GARMIN_PASSWORD = SYNC_CONFIG["GARMIN_PASSWORD"]
  GARMIN_AUTH_DOMAIN = SYNC_CONFIG["GARMIN_AUTH_DOMAIN"]
  GARMIN_NEWEST_NUM = SYNC_CONFIG["GARMIN_NEWEST_NUM"]
    
  garminClient = GarminClient(GARMIN_EMAIL, GARMIN_PASSWORD, GARMIN_AUTH_DOMAIN, GARMIN_NEWEST_NUM)

  COROS_EMAIL = SYNC_CONFIG["COROS_EMAIL"]
  COROS_PASSWORD = SYNC_CONFIG["COROS_PASSWORD"]
  corosClient = CorosClient(COROS_EMAIL, COROS_PASSWORD)
  corosClient.login()
  all_activities = safe_get_all(garminClient)
  logging.info(
      "Garmin auth mode for this run: %s (session dir: %s)",
      garminClient.session_source or "unknown",
      garminClient.session_dir,
  )

  # set SYNC_AFTER_DATE to a specific date in the format "YYYY-MM-DD" to filter activities after that date
  # SYNC_AFTER_DATE = os.getenv("SYNC_AFTER_DATE")
  SYNC_AFTER_DATE="2026-03-28"
  cutoff = datetime.fromisoformat(SYNC_AFTER_DATE) if SYNC_AFTER_DATE else None

  if all_activities == None or len(all_activities) == 0:
      exit()
  for activity in all_activities:
      activity_id = activity["activityId"]
      activity_name = get_activity_name(activity, garminClient)
      act_dt = None
      if cutoff:
        # common Garmin keys: "startTimeLocal" or "startTimeGMT" — adjust if different
        # dt_str = activity.get("startTimeLocal") or activity.get("startTimeGMT") or activity.get("startTime")
        dt_str = activity.get("startTimeLocal")
        if dt_str:
            try:
                act_dt = datetime.fromisoformat(dt_str.replace(" ", "T"))
            except Exception:
                # fallback: try a common format, adjust as needed
                act_dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
            if act_dt < cutoff:
                continue
    #   print(f"Processing activity ID: {activity_id}, Date: {act_dt if cutoff else 'N/A'}\n")
      garmin_db.saveActivity(activity_id, activity_name)

  un_sync_id_list = garmin_db.getUnSyncActivity()
  if un_sync_id_list == None or len(un_sync_id_list) == 0:
      exit()
  file_path_list = []
  
  for un_sync in un_sync_id_list:
    try:
      un_sync_id = un_sync["activity_id"]
      file = garminClient.downloadFitActivity(un_sync_id)
      file_path = os.path.join(GARMIN_FIT_DIR, f"{un_sync_id}.zip")
      with open(file_path, "wb") as fb:
          fb.write(file)

      un_sync_info = {
        "un_sync_id": un_sync_id,
        "file_path": file_path,
        "activity_name": un_sync.get("activity_name"),
      }

      file_path_list.append(un_sync_info)
      
    except Exception as err:
      print(err)
  for un_sync_info in file_path_list:
    try:
      client = None
      ## 中国区使用阿里云OSS
      if corosClient.regionId == 2:
         client = AliOssClient()
      elif corosClient.regionId == 1 or corosClient.regionId == 3:
         client = AwsOssClient()

      file_path = un_sync_info["file_path"]
      un_sync_id = un_sync_info["un_sync_id"]
      activity_name = un_sync_info.get("activity_name")
      print("activity_name: ", activity_name)
      oss_obj = client.multipart_upload(file_path,  f"{corosClient.userId}/{calculate_md5_file(file_path)}.zip")
      size = os.path.getsize(file_path)
      upload_result = corosClient.uploadActivity(
          f"fit_zip/{corosClient.userId}/{calculate_md5_file(file_path)}.zip",
          calculate_md5_file(file_path),
          f"{un_sync_id}.zip",
          size,
          activity_name=activity_name,
      )
      print(f"upload_result: {upload_result}\n")
      if upload_result:
          garmin_db.updateSyncStatus(un_sync_id)
    except Exception as err:
      print(err)
      garmin_db.updateExceptionSyncStatus(un_sync_id)
      exit()
