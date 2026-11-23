from setuptools import setup, find_packages

setup(
    name="hded_backup_manager",
    version="0.2.3",
    description="HDED Backup Manager for ERPNext 16",
    author="HDED",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
)
