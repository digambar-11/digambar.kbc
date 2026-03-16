import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AppPaths:
    app_data_dir: str
    config_path: str
    db_path: str
    downtime_csv_path: str
    backups_dir: str
    logs_dir: str
    support_dir: str
    license_cache_path: str


def _get_appdata_dir(app_folder_name: str = "NRC1") -> str:
    # Per-user data location on Windows.
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, app_folder_name)


def get_paths(app_folder_name: str = "NRC1") -> AppPaths:
    app_data_dir = _get_appdata_dir(app_folder_name)
    return AppPaths(
        app_data_dir=app_data_dir,
        config_path=os.path.join(app_data_dir, "config.ini"),
        db_path=os.path.join(app_data_dir, "cctv_manager.db"),
        downtime_csv_path=os.path.join(app_data_dir, "downtime_report.csv"),
        backups_dir=os.path.join(app_data_dir, "backups"),
        logs_dir=os.path.join(app_data_dir, "logs"),
        support_dir=os.path.join(app_data_dir, "support"),
        license_cache_path=os.path.join(app_data_dir, "license.json"),
    )


def ensure_dirs(paths: AppPaths) -> None:
    os.makedirs(paths.app_data_dir, exist_ok=True)
    os.makedirs(paths.backups_dir, exist_ok=True)
    os.makedirs(paths.logs_dir, exist_ok=True)
    os.makedirs(paths.support_dir, exist_ok=True)

