# social-mdeia
----------------------------------------------------------------------
# build mysqlclient trên Linux, bạn cần cài các package dev:
- sudo apt install python3-dev default-libmysqlclient-dev build-essential
-----------------------------------------------------------------------
# Install Version:
- pip install mysqlclient>=2.2.1
-----------------------------------------------------------------------
# Create Migrations:
- python manage.py makemigrations
------------------------------------------------------------------------
# Apply Migrations:
- python manage.py migrate
------------------------------------------------------------------------

# Run app: 
- python manage.py runserver 8080
------------------------------------------------------------------------
# Run app:
- uvicorn config.asgi:application --host 127.0.0.1 --port 8080
        
