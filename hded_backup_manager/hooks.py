app_name = "hded_backup_manager"
app_title = "HDED Backup Manager"
app_publisher = "HDED"
app_description = "Database-only backup and restore management for HDED ERPNext"
app_email = ""
app_license = "MIT"
app_version = "0.3.0"

add_to_apps_screen = [
    {
        "name": "hded_backup_manager",
        "logo": "/assets/hded_backup_manager/images/backup.svg",
        "title": "مدير النسخ الاحتياطي",
        "route": "/app/backup-manager",
    }
]

app_include_css = ["/assets/hded_backup_manager/css/backup_manager.css"]
