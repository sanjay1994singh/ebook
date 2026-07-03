# Ebook Django Backend

This backend handles:

- user register and login
- users/profile
- books/categories/chapters/pages
- favorite books
- reading progress
- Django admin panel for managing book data

## Setup

Use the bundled Python path if normal `python` is not available on this Windows machine.

```powershell
cd C:\Users\sanja\OneDrive\Documents\ebook\backend
& "C:\Users\sanja\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py createsuperuser
.\.venv\Scripts\python.exe manage.py runserver 0.0.0.0:8000
```

Your database is controlled from `backend/.env`.

For MySQL use:

```text
DB_ENGINE=mysql
DB_NAME=ebook
DB_USER=your_mysql_user
DB_PASSWORD=your_mysql_password
DB_HOST=127.0.0.1
DB_PORT=3306
```

For easy local testing without MySQL, use:

```text
DB_ENGINE=sqlite
```

This backend saves users, uploaded books, PDF files, chapters, pages, favorites, and reading progress in the selected database.

Local API:

```text
http://localhost:8000/api/books/
```

Android phone API on the same Wi-Fi:

```text
http://10.132.240.73:8000/api/books/
```

## Web App URLs

Laptop:

```text
http://localhost:8000/
http://localhost:8000/web/books/
```

Mobile browser on same Wi-Fi:

```text
http://10.132.240.73:8000/
http://10.132.240.73:8000/web/books/
```

## API URLs

- `POST /api/auth/register/`
- `POST /api/auth/login/`
- `POST /api/auth/token/refresh/`
- `GET /api/auth/me/`
- `GET /api/books/categories/`
- `GET /api/books/`
- `GET /api/books/<slug>/`
- `GET /api/books/<slug>/chapters/`
- `GET /api/books/pages/<id>/`
- `GET /api/books/favorites/`
- `POST /api/books/favorites/`
- `DELETE /api/books/favorites/<book_id>/`
- `GET /api/books/progress/`
- `POST /api/books/progress/`

## Upload PDF And Show In App

1. Start backend:

```powershell
.\.venv\Scripts\python.exe manage.py runserver 0.0.0.0:8000
```

2. Open admin:

```text
http://localhost:8000/admin/
```

3. Login with local test admin:

```text
username: admin
password: admin12345
```

4. Add or edit a book in `Library > Books`.
5. Fill title/category/language.
6. Upload PDF in `Pdf file`.
7. Keep `Auto extract pdf` checked.
8. Click Save.

The backend will extract readable PDF text and create:

- chapters from PDF bookmarks if available
- one fallback chapter named `पूर्ण पुस्तक` if PDF has no bookmarks
- book pages from the PDF text

Then both the React Native app and Django web app can load books, chapters, and page text from the same backend.

Note: scanned image PDFs may not have readable text. Those need OCR before text can appear in the reader.

## Web App

The web app uses the same backend uploaded content. No sample books are shown.

- Home page: `http://localhost:8000/`
- Book list: `http://localhost:8000/web/books/`
- Book detail: click any book
- Reader: click `प्रारंभ से पढ़ें` or any chapter in `विषय सूची`

## MySQL

After changing `.env`, run migrations again:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
```

React Native should call this backend API. The app should never connect directly to MySQL.
