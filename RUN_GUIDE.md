# Urgent Care Queue Dashboard Run Guide

## 中文版

### 1. 打开项目

打开 VS Code，然后打开项目文件夹：

```text
D:\Urgent Care Queue Dashboard Project
```

### 2. 启动 Backend

打开第一个 PowerShell terminal：

```powershell
cd "D:\Urgent Care Queue Dashboard Project"
```

如果是第一次运行，或者不确定依赖是否安装过，先运行：

```powershell
py -3 -m pip install -r backend_requirements.txt
```

设置 DeepSeek API key：

```powershell
$env:DEEPSEEK_API_KEY="你的 DeepSeek API Key"
```

启动 backend：

```powershell
py -3 -m uvicorn backend:app --host 0.0.0.0 --port 8001 --reload
```

如果看到下面的信息，说明 backend 成功运行：

```text
Application startup complete.
```

这个 terminal 不要关闭。

### 3. 启动 Flutter Frontend

打开第二个 PowerShell terminal。

如果 Flutter 没有永久加入 PATH，先运行：

```powershell
$env:Path += ";D:\Download\flutter_windows_3.44.4-stable\flutter\bin"
```

进入 Flutter 前端文件夹：

```powershell
cd "D:\Urgent Care Queue Dashboard Project\flutter_frontend"
```

安装 Flutter dependencies：

```powershell
flutter pub get
```

启动 Flutter Web：

```powershell
flutter run -d chrome
```

Chrome 会自动打开网页。如果没有自动打开，就复制 terminal 里显示的本地网址到浏览器。

### 4. 使用网站

网页左侧的 Backend API 保持：

```text
http://127.0.0.1:8001
```

然后可以使用：

- Patient check-in
- Risk Analysis and Join Queue
- Priority queue dashboard
- Notify Patient
- Start Consultation
- Mark as Completed
- Feedback Chatbot
- Feedback Alert Agent

### 5. 常见问题

如果提示：

```text
flutter is not recognized
```

说明 Flutter 没有加入 PATH。运行：

```powershell
$env:Path += ";D:\Download\flutter_windows_3.44.4-stable\flutter\bin"
```

如果提示：

```text
DEEPSEEK_API_KEY is missing
```

说明 backend terminal 没有设置 API key。重新运行：

```powershell
$env:DEEPSEEK_API_KEY="你的 DeepSeek API Key"
```

然后重启 backend。

### 6. 关机后重新打开

每次重新打开电脑后，至少需要重新做这两件事：

Terminal 1:

```powershell
cd "D:\Urgent Care Queue Dashboard Project"
$env:DEEPSEEK_API_KEY="你的 DeepSeek API Key"
py -3 -m uvicorn backend:app --host 0.0.0.0 --port 8001 --reload
```

Terminal 2:

```powershell
$env:Path += ";D:\Download\flutter_windows_3.44.4-stable\flutter\bin"
cd "D:\Urgent Care Queue Dashboard Project\flutter_frontend"
flutter run -d chrome
```

---

## English Version

### 1. Open the Project

Open VS Code and open this project folder:

```text
D:\Urgent Care Queue Dashboard Project
```

### 2. Start the Backend

Open the first PowerShell terminal:

```powershell
cd "D:\Urgent Care Queue Dashboard Project"
```

If this is the first time running the project, or if you are not sure whether the dependencies are installed, run:

```powershell
py -3 -m pip install -r backend_requirements.txt
```

Set the DeepSeek API key:

```powershell
$env:DEEPSEEK_API_KEY="your DeepSeek API Key"
```

Start the backend:

```powershell
py -3 -m uvicorn backend:app --host 0.0.0.0 --port 8001 --reload
```

If you see this message, the backend is running successfully:

```text
Application startup complete.
```

Do not close this terminal.

### 3. Start the Flutter Frontend

Open a second PowerShell terminal.

If Flutter has not been permanently added to PATH, run:

```powershell
$env:Path += ";D:\Download\flutter_windows_3.44.4-stable\flutter\bin"
```

Go to the Flutter frontend folder:

```powershell
cd "D:\Urgent Care Queue Dashboard Project\flutter_frontend"
```

Install Flutter dependencies:

```powershell
flutter pub get
```

Run Flutter Web:

```powershell
flutter run -d chrome
```

Chrome should open automatically. If it does not, copy the local URL shown in the terminal and open it in the browser.

### 4. Use the Website

Keep the Backend API field as:

```text
http://127.0.0.1:8001
```

The system supports:

- Patient check-in
- Risk Analysis and Join Queue
- Priority queue dashboard
- Notify Patient
- Start Consultation
- Mark as Completed
- Feedback Chatbot
- Feedback Alert Agent

### 5. Common Issues

If you see:

```text
flutter is not recognized
```

Flutter is not available in PATH. Run:

```powershell
$env:Path += ";D:\Download\flutter_windows_3.44.4-stable\flutter\bin"
```

If you see:

```text
DEEPSEEK_API_KEY is missing
```

The backend terminal does not have the API key set. Run:

```powershell
$env:DEEPSEEK_API_KEY="your DeepSeek API Key"
```

Then restart the backend.

### 6. Restart After Shutting Down the Computer

After restarting the computer, you usually need to run these commands again:

Terminal 1:

```powershell
cd "D:\Urgent Care Queue Dashboard Project"
$env:DEEPSEEK_API_KEY="your DeepSeek API Key"
py -3 -m uvicorn backend:app --host 0.0.0.0 --port 8001 --reload
```

Terminal 2:

```powershell
$env:Path += ";D:\Download\flutter_windows_3.44.4-stable\flutter\bin"
cd "D:\Urgent Care Queue Dashboard Project\flutter_frontend"
flutter run -d chrome
```
