import logging
import os
import time
from enum import Enum, auto
import requests

import garth

from .garmin_url_dict import GARMIN_URL_DICT

try:
    from config import DB_DIR
except ImportError:
    from scripts.config import DB_DIR

logger = logging.getLogger(__name__)


class GarminClient:
  BROWSER_USER_AGENT = (
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36"
  )

  def __init__(self, email, password, auth_domain, newest_num):
        self.auth_domain = auth_domain
        self.email = email
        self.password = password
        self.garthClient = garth
        self.newestNum = int(newest_num)
        self.session_source = None
        self.session_seeded_from_env = False
        self.session_dir = os.path.abspath(
            os.getenv("GARTH_HOME") or os.path.join(DB_DIR, ".garth")
        )
        self.login_retry_after = 0
        self.last_login_error = None
        self.headers = {
            "User-Agent": self.BROWSER_USER_AGENT,
            "origin": GARMIN_URL_DICT.get("SSO_URL_ORIGIN"),
            "nk": "NT"
        }

  def _configure_domain(self):
      if self.auth_domain and str(self.auth_domain).upper() == "CN":
          self.garthClient.configure(domain="garmin.cn")

  def _apply_browser_user_agent(self):
      try:
          self.garthClient.client.sess.headers["User-Agent"] = self.BROWSER_USER_AGENT
      except Exception:
          logger.debug("Unable to override Garmin session User-Agent before login.")

  def _token_file(self, name):
      return os.path.join(self.session_dir, name)

  def _session_files_exist(self):
      return all(
          os.path.exists(self._token_file(name))
          for name in ("oauth1_token.json", "oauth2_token.json")
      )

  def _seed_session_from_env(self):
      if self._session_files_exist():
          return True

      oauth1 = os.getenv("GARTH_OAUTH1_TOKEN_JSON")
      oauth2 = os.getenv("GARTH_OAUTH2_TOKEN_JSON")
      if not oauth1 or not oauth2:
          return False

      os.makedirs(self.session_dir, exist_ok=True)
      with open(self._token_file("oauth1_token.json"), "w", encoding="utf-8") as fh:
          fh.write(oauth1.strip())
      with open(self._token_file("oauth2_token.json"), "w", encoding="utf-8") as fh:
          fh.write(oauth2.strip())
      self.session_seeded_from_env = True
      logger.info("Seeded Garmin session files from environment into %s", self.session_dir)
      return True

  def _clear_session_files(self):
      for name in ("oauth1_token.json", "oauth2_token.json"):
          token_path = self._token_file(name)
          if os.path.exists(token_path):
              os.remove(token_path)

  def _resume_saved_session(self):
      self.session_seeded_from_env = False
      self._seed_session_from_env()
      if not self._session_files_exist():
          return False

      self._configure_domain()
      self._apply_browser_user_agent()
      self.garthClient.resume(self.session_dir)
      self._apply_browser_user_agent()
      _ = self.garthClient.client.username
      self.session_source = "env-seeded" if self.session_seeded_from_env else "on-disk"
      return True

  def _persist_session(self):
      os.makedirs(self.session_dir, exist_ok=True)
      self.garthClient.save(self.session_dir)

  def ensure_session(self):
      try:
          _ = self.garthClient.client.username
          self.last_login_error = None
          self.login_retry_after = 0
          self.session_source = "in-memory"
          logger.info("Using active in-memory Garmin session.")
          return
      except Exception:
          pass

      if self.last_login_error and time.time() < self.login_retry_after:
          raise RuntimeError(
              "Garmin login recently failed; refusing to retry immediately."
          ) from self.last_login_error

      try:
          if self._resume_saved_session():
              logger.info(
                  "Using %s Garmin session from %s",
                  self.session_source,
                  self.session_dir,
              )
              self.last_login_error = None
              self.login_retry_after = 0
              return
      except Exception as exc:
          logger.warning(
              "Failed to resume Garmin session from %s: %s: %r",
              self.session_dir,
              type(exc).__name__,
              exc,
          )
          self._clear_session_files()

      logger.warning("Garmin is not logging in or the token has expired.")
      self._configure_domain()
      self._apply_browser_user_agent()
      self.session_source = "fresh-login"
      logger.info("Attempting fresh Garmin username/password login.")

      try:
          self.garthClient.login(self.email, self.password)
          self._persist_session()
          logger.info("Saved Garmin session to %s", self.session_dir)
          self.last_login_error = None
          self.login_retry_after = 0
      except Exception as exc:
          self.last_login_error = exc
          self.login_retry_after = time.time() + 300
          raise
  
  ## 登录装饰器
  def login(func):    
    def ware(self, *args, **kwargs):    
      self.ensure_session()
      return func(self, *args, **kwargs)
    return ware
  
  @login 
  def download(self, path, **kwargs):
     return self.garthClient.download(path, **kwargs)
  
  @login 
  def connectapi(self, path, **kwargs):
      return self.garthClient.connectapi(path, **kwargs)
     

  ## 获取运动
  def getActivities(self, start:int, limit:int):
     
     params = {"start": str(start), "limit": str(limit)}
     activities =  self.connectapi(path=GARMIN_URL_DICT["garmin_connect_activities"], params=params)
     return activities;

  def getActivity(self, activity_id:int):
     activity_url = f"{GARMIN_URL_DICT['garmin_connect_activity']}/{activity_id}"
     return self.connectapi(path=activity_url)

  # ## 获取所有运动
  # def getAllActivities(self): 
  #   all_activities = []
  #   start = 0
  #   limit=100
  #   if 0 < self.newestNum < 100:
  #     limit = self.newestNum
      
  #   while(True):
  #     activities = self.getActivities(start=start, limit=limit)
  #     if len(activities) > 0:
  #       all_activities.extend(activities)
        
  #       if 0 < self.newestNum < 100 or start > self.newestNum:
  #          return all_activities
  #     else:
  #        return all_activities
  #     start += limit

  ## 获取所有运动
  def getAllActivities(self): 
    all_activities = []
    start = 0
    while(True):
      activities = self.getActivities(start=start, limit=100)
      if len(activities) > 0:
         all_activities.extend(activities)
      else:
         return all_activities
      start += 100

  ## 下载原始格式的运动
  def downloadFitActivity(self, activity):
    download_fit_activity_url_prefix = GARMIN_URL_DICT["garmin_connect_fit_download"]
    download_fit_activity_url = f"{download_fit_activity_url_prefix}/{activity}"
    response = self.download(download_fit_activity_url)
    return response

  @login  
  def upload_activity(self, activity_path: str):
    """Upload activity in fit format from file."""
    # This code is borrowed from python-garminconnect-enhanced ;-)
    file_base_name = os.path.basename(activity_path)
    file_extension = file_base_name.split(".")[-1]
    allowed_file_extension = (
        file_extension.upper() in ActivityUploadFormat.__members__
    )

    if allowed_file_extension:
       try:
        with open(activity_path, 'rb') as file:
          file_data = file.read()
          fields = {
              'file': (file_base_name, file_data, 'text/plain')
          }

          url_path = GARMIN_URL_DICT["garmin_connect_upload"]
          upload_url = f"https://connectapi.{self.garthClient.client.domain}{url_path}"
          self.headers['Authorization'] = str(self.garthClient.client.oauth2_token)
          response = requests.post(upload_url, headers=self.headers, files=fields)
          res_code = response.status_code
          result = response.json()
          uploadId =  result.get("detailedImportResult").get('uploadId')
          isDuplicateUpload = uploadId == None or uploadId == ''
          if res_code == 202 and not isDuplicateUpload:
              status = "SUCCESS"
          elif res_code == 409 and result.get("detailedImportResult").get("failures")[0].get('messages')[0].get('content') == "Duplicate Activity.":
              status = "DUPLICATE_ACTIVITY" 
       except Exception as e:
            print(e)
            status = "UPLOAD_EXCEPTION"
       finally:
            return status
    else:
        return "UPLOAD_EXCEPTION"
  

class ActivityUploadFormat(Enum):
  FIT = auto()
  GPX = auto()
  TCX = auto()

class GarminNoLoginException(Exception):
    """Raised when rate limit is exceeded."""

    def __init__(self, status):
        """Initialize."""
        super(GarminNoLoginException, self).__init__(status)
        self.status = status
