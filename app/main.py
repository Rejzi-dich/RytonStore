from fastapi import FastAPI, Request, Form, HTTPException, Depends, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import httpx
import json
import os
import requests
from typing import List, Optional
from jose import jwt
from datetime import datetime, timedelta
import secrets

app = FastAPI(title="Ryton Store")

# этот блок для Vercel
from mangum import Mangum
handler = Mangum(app)

# Настройки OAuth
from dotenv import load_dotenv

# Загружаем переменные из .env.local только в локальной среде
if os.path.exists(".env.local"):
    load_dotenv(".env.local")

GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET")

GITHUB_REDIRECT_URI = "http://localhost:8000/auth/github/callback"

# Настройки JWT
SECRET_KEY = os.environ.get("SECRET_KEY", secrets.token_hex(32))
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 1 день

# Подключаем статические файлы и шаблоны
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Загружаем список пакетов
def load_packages():
    if os.path.exists("packages.json"):
        with open("packages.json", "r") as f:
            return json.load(f)
    return []

# Сохраняем список пакетов
def save_packages(packages):
    with open("packages.json", "w") as f:
        json.dump(packages, f, indent=2)

# Функция для получения текущего пользователя
async def get_current_user(session: Optional[str] = Cookie(None)):
    if not session:
        return None
    
    try:
        payload = jwt.decode(session, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except:
        return None

@app.get("/update-package/{package_id}")
async def update_package(package_id: int, user: dict = Depends(get_current_user)):
    if not user:
        return RedirectResponse(url="/login/github")
    
    packages = load_packages()
    
    if package_id < 0 or package_id >= len(packages):
        raise HTTPException(status_code=404, detail="Package not found")
    
    package = packages[package_id]
    
    # Проверяем, принадлежит ли пакет пользователю
    if package.get("owner", {}).get("login") != user["login"] and package.get("submitted_by") != user["login"]:
        raise HTTPException(status_code=403, detail="You don't have permission to update this package")
    
    # Обновляем данные пакета из GitHub
    packages[package_id] = update_package_from_github(package)
    save_packages(packages)
    
    return RedirectResponse(url="/my-packages")

def get_github_reviews(repo_owner, repo_name, limit=10):
    """Получает последние отзывы из GitHub Issues с меткой 'review'"""
    # Формируем URL для API GitHub
    issues_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/issues?labels=review&state=all&sort=created&direction=desc&per_page={limit}"
    
    # Добавляем токен GitHub, если он есть
    headers = {}
    github_token = os.environ.get("GITHUB_TOKEN")
    if github_token:
        headers["Authorization"] = f"token {github_token}"
    
    try:
        response = requests.get(issues_url, headers=headers)
        if response.status_code != 200:
            return []
        
        issues = response.json()
        reviews = []
        
        for issue in issues:
            # Форматируем дату
            created_at = issue.get("created_at", "")
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                formatted_date = dt.strftime("%d %b %Y")
            except:
                formatted_date = created_at
            
            # Создаем объект отзыва
            review = {
                "title": issue.get("title", "").replace("Review: ", ""),
                "body": issue.get("body", ""),
                "author": issue.get("user", {}).get("login", ""),
                "author_avatar": issue.get("user", {}).get("avatar_url", ""),
                "created_at": formatted_date,
                "url": issue.get("html_url", ""),
                "state": issue.get("state", "open")
            }
            reviews.append(review)
        
        return reviews
    except Exception as e:
        print(f"Error fetching reviews: {e}")
        return []

def update_package_from_github(package):
    """Обновляет данные пакета из GitHub API"""
    if not package.get("github_url"):
        return package
    
    # Получаем свежие данные из GitHub
    repo_info = get_github_repo_info(package["github_url"])
    if not repo_info:
        return package
    
    # Обновляем только те поля, которые должны парситься из GitHub
    package["owner"] = repo_info["owner"]
    package["stars"] = repo_info["stars"]
    package["forks"] = repo_info["forks"]
    package["watchers"] = repo_info["watchers"]
    package["language"] = repo_info["language"]
    package["open_issues"] = repo_info["open_issues"]
    package["created_at"] = repo_info["created_at"]
    package["updated_at"] = repo_info["updated_at"]
    package["version"] = repo_info["release"].get("version", package.get("version", ""))
    package["download_url"] = repo_info["release"].get("download_url", package.get("download_url", ""))
    package["published_at"] = repo_info["release"].get("published_at", package.get("published_at", ""))
    package["release_notes"] = repo_info["release"].get("body", package.get("release_notes", ""))
    
    return package

# Получаем информацию о репозитории с GitHub
def get_github_repo_info(repo_url):
    """Получает информацию о репозитории с GitHub"""
    # Извлекаем имя пользователя и репозитория из URL
    parts = repo_url.strip("/").split("/")
    if "github.com" not in parts:
        return None
    
    username_index = parts.index("github.com") + 1
    if username_index >= len(parts):
        return None
    
    username = parts[username_index]
    repo_name = parts[username_index + 1] if username_index + 1 < len(parts) else None
    
    if not repo_name:
        return None
    
    # Получаем данные через GitHub API
    headers = {}
    # Если есть токен GitHub, используем его для увеличения лимита запросов
    github_token = os.environ.get("GITHUB_TOKEN")
    if github_token:
        headers["Authorization"] = f"token {github_token}"
    
    # Получаем данные о репозитории
    api_url = f"https://api.github.com/repos/{username}/{repo_name}"
    try:
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()  # Вызовет исключение при ошибке HTTP
        data = response.json()
    except Exception as e:
        print(f"Error fetching repo data: {e}")
        return None
    
    # Получаем последний релиз
    releases_url = f"https://api.github.com/repos/{username}/{repo_name}/releases/latest"
    try:
        releases_response = requests.get(releases_url, headers=headers)
        release_data = {}
        if releases_response.status_code == 200:
            release_data = releases_response.json()
    except Exception as e:
        print(f"Error fetching release data: {e}")
        release_data = {}
    
    # Получаем информацию о пользователе
    user_url = f"https://api.github.com/users/{username}"
    try:
        user_response = requests.get(user_url, headers=headers)
        user_data = {}
        if user_response.status_code == 200:
            user_data = user_response.json()
    except Exception as e:
        print(f"Error fetching user data: {e}")
        user_data = {}

    if user_response.status_code == 200:
        user_data = user_response.json()

    # Список доверенных разработчиков
    trusted_developers = ["trusted_dev1", "trusted_dev2", "trusted_dev3"]
    clteam_members = ["Rejzi-dich", "CodeLibraty"]
    
    # Определяем статус разработчика
    developer_status = None
    if username in clteam_members:
        developer_status = "CLteam Member"
    elif username in trusted_developers:
        developer_status = "Trusted Developer"

    # Получаем темы репозитория
    topics_url = f"https://api.github.com/repos/{username}/{repo_name}/topics"
    headers["Accept"] = "application/vnd.github.mercy-preview+json"
    
    try:
        topics_response = requests.get(topics_url, headers=headers)
        all_topics = []
        if topics_response.status_code == 200:
            all_topics = topics_response.json().get("names", [])
        
        # Фильтруем темы, оставляя только разрешенные
        filtered_topics = [topic for topic in all_topics if topic in ALLOWED_TAGS]
        
        # Если нет разрешенных тем, добавляем "other"
        if not filtered_topics and all_topics:
            filtered_topics = ["other"]
    except:
        filtered_topics = []

    # Форматируем даты для лучшего отображения
    def format_date(date_str):
        if not date_str:
            return "N/A"
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return dt.strftime("%d %b %Y")
        except:
            return date_str
    
    return {
        "name": data.get("name", repo_name),
        "description": data.get("description", ""),
        "stars": data.get("stargazers_count", 0),
        "topics": filtered_topics,
        "all_topics": all_topics,  # Сохраняем все темы для информации
        "forks": data.get("forks_count", 0),
        "watchers": data.get("watchers_count", 0),
        "language": data.get("language", ""),
        "open_issues": data.get("open_issues_count", 0),
        "created_at": format_date(data.get("created_at", "")),
        "updated_at": format_date(data.get("updated_at", "")),
        "github_url": repo_url,
        "owner": {
            "login": username,
            "avatar_url": user_data.get("avatar_url", data.get("owner", {}).get("avatar_url", "")),
            "name": user_data.get("name", ""),
            "bio": user_data.get("bio", ""),
            "status": developer_status
        },
        "release": {
            "version": release_data.get("tag_name", ""),
            "published_at": format_date(release_data.get("published_at", "")),
            "download_url": next((asset["browser_download_url"] for asset in release_data.get("assets", []) 
                                if asset["name"].endswith(".ryx")), ""),
            "body": release_data.get("body", "")
        }
    }

@app.get("/api/user/repos")
async def get_user_repos(user: dict = Depends(get_current_user)):
    if not user or "access_token" not in user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Получаем репозитории пользователя
    repos_url = "https://api.github.com/user/repos?sort=updated&per_page=100"
    headers = {
        "Authorization": f"token {user['access_token']}",
        "Accept": "application/json"
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.get(repos_url, headers=headers)
        repos_data = response.json()
    
    # Получаем репозитории организаций пользователя
    orgs_url = "https://api.github.com/user/orgs"
    async with httpx.AsyncClient() as client:
        response = await client.get(orgs_url, headers=headers)
        orgs_data = response.json()
    
    org_repos = []
    for org in orgs_data:
        org_repos_url = f"https://api.github.com/orgs/{org['login']}/repos?per_page=100"
        async with httpx.AsyncClient() as client:
            response = await client.get(org_repos_url, headers=headers)
            org_repos.extend(response.json())
    
    # Объединяем и форматируем данные
    all_repos = repos_data + org_repos
    formatted_repos = []
    
    for repo in all_repos:
        formatted_repos.append({
            "name": repo["name"],
            "description": repo["description"],
            "html_url": repo["html_url"],
            "stars": repo["stargazers_count"],
            "language": repo["language"],
            "owner": repo["owner"]["login"]
        })
    
    # Сортируем по количеству звезд
    formatted_repos.sort(key=lambda x: x["stars"], reverse=True)
    
    return formatted_repos

@app.get("/my-packages", response_class=HTMLResponse)
async def my_packages(request: Request, user: dict = Depends(get_current_user)):
    if not user:
        return RedirectResponse(url="/login/github")
    
    packages = load_packages()
    
    # Фильтруем пакеты, принадлежащие пользователю
    user_packages = []
    for i, package in enumerate(packages):
        if package.get("owner", {}).get("login") == user["login"] or package.get("submitted_by") == user["login"]:
            package["index"] = i  # Добавляем индекс для ссылок
            user_packages.append(package)
    
    return templates.TemplateResponse("my_packages.html", {
        "request": request,
        "packages": user_packages,
        "user": user
    })

# Функция для создания JWT токена
def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# Маршрут для входа через GitHub
@app.get("/login/github")
async def login_github():
    github_auth_url = f"https://github.com/login/oauth/authorize?client_id={GITHUB_CLIENT_ID}&redirect_uri={GITHUB_REDIRECT_URI}&scope=user%20repo"
    return RedirectResponse(github_auth_url)

# Обработчик callback от GitHub
@app.get("/auth/github/callback")
async def github_callback(code: str):
    # Обмен кода на токен доступа
    token_url = "https://github.com/login/oauth/access_token"
    data = {
        "client_id": GITHUB_CLIENT_ID,
        "client_secret": GITHUB_CLIENT_SECRET,
        "code": code,
        "redirect_uri": GITHUB_REDIRECT_URI
    }
    headers = {"Accept": "application/json"}
    
    async with httpx.AsyncClient() as client:
        response = await client.post(token_url, data=data, headers=headers)
        token_data = response.json()
    
    if "access_token" not in token_data:
        raise HTTPException(status_code=400, detail="Could not get access token")
    
    access_token = token_data["access_token"]
    
    # Получение информации о пользователе
    user_url = "https://api.github.com/user"
    headers = {
        "Authorization": f"token {access_token}",
        "Accept": "application/json"
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.get(user_url, headers=headers)
        user_data = response.json()
    
    # Создание JWT токена
    token_data = {
        "github_id": user_data["id"],
        "login": user_data["login"],
        "name": user_data.get("name", ""),
        "avatar_url": user_data.get("avatar_url", ""),
        "access_token": access_token
    }
    
    jwt_token = create_access_token(token_data)
    
    # Создаем ответ с установкой cookie
    response = RedirectResponse(url="/")
    response.set_cookie(key="session", value=jwt_token, httponly=True, max_age=60*60*24)
    
    return response

# Маршрут для выхода
@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/")
    response.delete_cookie(key="session")
    return response

# Функция для проверки принадлежности репозитория пользователю
async def check_repo_ownership(repo_url: str, user_data: dict):
    if not user_data or "access_token" not in user_data:
        return False
    
    # Извлекаем имя пользователя и репозитория из URL
    parts = repo_url.strip("/").split("/")
    if "github.com" not in parts:
        return False
    
    username_index = parts.index("github.com") + 1
    if username_index >= len(parts):
        return False
    
    repo_owner = parts[username_index]
    repo_name = parts[username_index + 1] if username_index + 1 < len(parts) else None
    
    if not repo_name:
        return False
    
    # Проверяем, принадлежит ли репозиторий пользователю
    if repo_owner.lower() == user_data["login"].lower():
        return True
    
    # Проверяем, принадлежит ли репозиторий организации пользователя
    orgs_url = "https://api.github.com/user/orgs"
    headers = {
        "Authorization": f"token {user_data['access_token']}",
        "Accept": "application/json"
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.get(orgs_url, headers=headers)
        orgs_data = response.json()
    
    for org in orgs_data:
        if org["login"].lower() == repo_owner.lower():
            return True
    
    return False

# Обновляем маршрут главной страницы
@app.get("/", response_class=HTMLResponse)
async def home(request: Request, q: Optional[str] = None, user: dict = Depends(get_current_user)):
    packages = load_packages()
    
    # Фильтрация по поисковому запросу
    if q:
        packages = [pkg for pkg in packages if q.lower() in pkg["name"].lower() or 
                   (pkg.get("description") and q.lower() in pkg["description"].lower())]
    
    return templates.TemplateResponse("index.html", {
        "request": request,
        "packages": packages,
        "search_query": q,
        "user": user
    })

@app.get("/categories", response_class=HTMLResponse)
async def categories(request: Request, user: dict = Depends(get_current_user)):
    packages = load_packages()
    
    # Собираем статистику по тегам
    tag_stats = {}
    for package in packages:
        for topic in package.get("topics", []):
            if topic in tag_stats:
                tag_stats[topic] += 1
            else:
                tag_stats[topic] = 1
    
    # Сортируем теги по количеству пакетов
    sorted_tags = sorted(tag_stats.items(), key=lambda x: x[1], reverse=True)
    
    return templates.TemplateResponse("categories.html", {
        "request": request,
        "tags": sorted_tags,
        "user": user
    })

@app.get("/admin/update-all-packages", response_class=HTMLResponse)
async def update_all_packages(request: Request):
    packages = load_packages()
    updated_count = 0
    
    for i, package in enumerate(packages):
        updated_package = update_package_from_github(package)
        if updated_package != package:
            packages[i] = updated_package
            updated_count += 1
    
    save_packages(packages)
    
    return templates.TemplateResponse("admin_message.html", {
        "request": request,
        "message": f"Updated {updated_count} packages from GitHub"
    })


@app.get("/package/{package_id}", response_class=HTMLResponse)
async def package_details(request: Request, package_id: int, user: dict = Depends(get_current_user)):
    packages = load_packages()
    
    if package_id < 0 or package_id >= len(packages):
        raise HTTPException(status_code=404, detail="Package not found")
    
    # Обновляем данные пакета из GitHub перед отображением
    packages[package_id] = update_package_from_github(packages[package_id])
    save_packages(packages)
    
    package = packages[package_id]
    
    # Вычисляем процент для прогресс-бара
    stars_percent = min(package.get("stars", 0), 100)
    
    # Получаем отзывы из GitHub
    reviews = []
    if package.get("github_url"):
        # Извлекаем имя пользователя и репозитория из URL
        parts = package["github_url"].strip("/").split("/")
        if "github.com" in parts:
            username_index = parts.index("github.com") + 1
            if username_index < len(parts) - 1:
                repo_owner = parts[username_index]
                repo_name = parts[username_index + 1]
                reviews = get_github_reviews(repo_owner, repo_name, limit=10)
    
    return templates.TemplateResponse("package.html", {
        "request": request,
        "package": package,
        "package_id": package_id,
        "user": user,
        "stars_percent": stars_percent,
        "reviews": reviews
    })

# Обновляем маршрут добавления пакета
@app.get("/add", response_class=HTMLResponse)
async def add_package_form(request: Request, user: dict = Depends(get_current_user)):
    if not user:
        return RedirectResponse(url="/login/github")
    
    return templates.TemplateResponse("add_package.html", {
        "request": request,
        "user": user
    })

@app.post("/add")
async def add_package(request: Request, github_url: str = Form(...), user: dict = Depends(get_current_user)):
    if not user:
        return RedirectResponse(url="/login/github")
    
    # Проверяем принадлежность репозитория
    is_owner = await check_repo_ownership(github_url, user)
    if not is_owner:
        return templates.TemplateResponse("add_package.html", {
            "request": request,
            "user": user,
            "error": "You can only add repositories that belong to you or your organizations"
        })
    
    # Получаем информацию о репозитории
    repo_info = get_github_repo_info(github_url)
    
    if not repo_info:
        return templates.TemplateResponse("add_package.html", {
            "request": request,
            "user": user,
            "error": "Invalid GitHub repository"
        })
    
    # Создаем запись о пакете
    new_package = {
        "name": repo_info["name"],
        "description": repo_info["description"],
        "github_url": github_url,
        "stars": repo_info["stars"],
        "forks": repo_info.get("forks", 0),
        "watchers": repo_info.get("watchers", 0),
        "language": repo_info.get("language", ""),
        "open_issues": repo_info.get("open_issues", 0),
        "created_at": repo_info.get("created_at", ""),
        "updated_at": repo_info.get("updated_at", ""),
        "owner": repo_info["owner"],
        "version": repo_info["release"].get("version", ""),
        "download_url": repo_info["release"].get("download_url", ""),
        "published_at": repo_info["release"].get("published_at", ""),
        "release_notes": repo_info["release"].get("body", ""),
        "submitted_by": user["login"]
    }
    
    # Добавляем пакет в список
    packages = load_packages()
    packages.append(new_package)
    save_packages(packages)
    
    # Перенаправляем на главную страницу
    return RedirectResponse(url="/", status_code=303)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
