from setuptools import setup, find_packages
import os

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="tarxemo-django-stripe",
    version="0.1.0",
    author="TarXemo",
    author_email="info@tarxemo.com",
    description="A professional Django library for integrating Stripe payments, refunds, and subscriptions",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/tarxemo/tarxemo-django-stripe",
    project_urls={
        "Bug Tracker": "https://github.com/tarxemo/tarxemo-django-stripe/issues",
        "Source Code": "https://github.com/tarxemo/tarxemo-django-stripe",
        "Documentation": "https://github.com/tarxemo/tarxemo-django-stripe/blob/main/README.md",
    },
    packages=find_packages(exclude=["tests*", "bhumwi*"]),
    include_package_data=True,
    install_requires=[
        "Django>=3.2",
        "stripe>=8.0.0",
    ],
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Web Environment",
        "Framework :: Django",
        "Framework :: Django :: 3.2",
        "Framework :: Django :: 4.0",
        "Framework :: Django :: 5.0",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    python_requires=">=3.10",
    zip_safe=False,
    keywords="django stripe payments subcriptions multi-currency gateway",
)
