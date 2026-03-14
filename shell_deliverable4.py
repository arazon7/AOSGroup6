import os
import shlex
import subprocess
import json
import getpass
from pathlib import Path

jobs = []
job_counter = 1

# -----------------------------
# In-memory user database
# -----------------------------
users_db = {
    "admin": {"password": "admin123", "role": "admin"},
    "student": {"password": "student123", "role": "user"},
}

current_user = None

PERM_FILE = Path(__file__).with_name("permissions_db.json")
permissions_db = {}


def normalize_path(path_str):
    return os.path.abspath(os.path.expanduser(path_str))


def split_pipeline(command_line):
    parts = []
    current = []
    single = False
    double = False

    for ch in command_line:
        if ch == "'" and not double:
            single = not single
        elif ch == '"' and not single:
            double = not double

        if ch == "|" and not single and not double:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)

    if current:
        parts.append("".join(current).strip())

    return parts


def load_permissions():
    global permissions_db
    if PERM_FILE.exists():
        try:
            permissions_db = json.loads(PERM_FILE.read_text())
        except:
            permissions_db = {}


def save_permissions():
    PERM_FILE.write_text(json.dumps(permissions_db, indent=2))


def set_permissions(path_str, admin_perm, user_perm):
    abs_path = normalize_path(path_str)
    permissions_db[abs_path] = {
        "admin": admin_perm,
        "user": user_perm
    }
    save_permissions()


def get_permissions(path_str):
    abs_path = normalize_path(path_str)

    if abs_path in permissions_db:
        return permissions_db[abs_path]

    if os.path.isdir(abs_path):
        return {"admin": "rwx", "user": "rwx"}

    return {"admin": "rwx", "user": "rw"}


def has_permission(path_str, action):
    role = current_user["role"]
    perms = get_permissions(path_str)

    role_key = "admin" if role == "admin" else "user"
    allowed = perms.get(role_key, "")

    return action in allowed


def ensure_demo_security_files():
    system_dir = normalize_path("system_files")

    if not os.path.exists(system_dir):
        os.mkdir(system_dir)

    config_file = os.path.join(system_dir, "config.txt")

    if not os.path.exists(config_file):
        with open(config_file, "w") as f:
            f.write("system configuration\n")

    set_permissions(system_dir, "rwx", "rx")
    set_permissions(config_file, "rw", "r")


# -----------------------------
# Authentication
# -----------------------------
def login_prompt():
    global current_user

    while True:
        print("\nLogin required")

        username = input("Username: ").strip()
        password = getpass.getpass("Password: ")

        user = users_db.get(username)

        if user and user["password"] == password:
            current_user = {"username": username, "role": user["role"]}
            print(f"Login successful. Logged in as {username} ({user['role']})")
            return

        print("Invalid credentials. Try again.")


def add_user(username, password, role):
    users_db[username] = {"password": password, "role": role}


def update_jobs():
    for job in jobs:
        if job["status"] == "Running":
            if job["process"].poll() is not None:
                job["status"] = "Finished"


def find_job_by_id(job_id):
    for job in jobs:
        if job["job_id"] == job_id:
            return job
    return None


def builtin_help():
    return """
Available commands:
 cd [dir]
 pwd
 exit
 echo
 clear
 ls
 cat
 mkdir
 rmdir
 rm
 touch
 jobs
 kill
 fg
 bg
 whoami
 showperm
 chmodsim
 login
 logout
 adduser
 listusers
 help
"""


def run_builtin(args, input_data=None):

    cmd = args[0]

    if cmd == "pwd":
        return os.getcwd() + "\n"

    elif cmd == "whoami":
        return f'{current_user["username"]} ({current_user["role"]})\n'

    elif cmd == "echo":
        return " ".join(args[1:]) + "\n"

    elif cmd == "ls":
        path = args[1] if len(args) > 1 else "."
        try:
            files = os.listdir(path)
            return "\n".join(files) + "\n"
        except:
            return "ls error\n"

    elif cmd == "cat":
        file = args[1]

        if not has_permission(file, "r"):
            return "permission denied\n"

        try:
            with open(file) as f:
                return f.read()
        except:
            return "cat error\n"

    elif cmd == "mkdir":
        os.mkdir(args[1])
        return None

    elif cmd == "rm":
        target = args[1]

        if not has_permission(target, "w"):
            return "permission denied\n"

        try:
            os.remove(target)
        except:
            return "rm error\n"

    elif cmd == "touch":
        open(args[1], "a").close()
        return None

    elif cmd == "jobs":
        update_jobs()
        out = []
        for job in jobs:
            out.append(f'[{job["job_id"]}] {job["pid"]} {job["status"]}')
        return "\n".join(out) + "\n"

    elif cmd == "kill":
        pid = int(args[1])
        os.system(f"taskkill /PID {pid} /F >nul 2>&1")
        return "process terminated\n"

    elif cmd == "adduser":

        if current_user["role"] != "admin":
            return "only admin can add users\n"

        username = args[1]
        password = args[2]
        role = args[3]

        add_user(username, password, role)

        return "user added\n"

    elif cmd == "listusers":

        lines = []
        for u in users_db:
            lines.append(f"{u} ({users_db[u]['role']})")

        return "\n".join(lines) + "\n"

    elif cmd == "login":
        login_prompt()
        return None

    elif cmd == "logout":
        login_prompt()
        return None

    elif cmd == "help":
        return builtin_help()

    return None


BUILTINS = {
    "pwd", "exit", "echo", "clear", "ls", "cat", "mkdir",
    "rm", "touch", "jobs", "kill", "whoami",
    "login", "logout", "adduser", "listusers", "help"
}


def run_pipeline(command_line):

    stages = split_pipeline(command_line)
    data = None

    for stage in stages:

        args = shlex.split(stage)
        cmd = args[0]

        if cmd in BUILTINS:

            output = run_builtin(args, data)

            data = output if output else ""

        else:

            result = subprocess.run(
                stage,
                input=data,
                text=True,
                capture_output=True,
                shell=True
            )

            data = result.stdout

    return data


def main():

    global job_counter

    load_permissions()
    ensure_demo_security_files()

    login_prompt()

    while True:

        update_jobs()

        command = input(f'{current_user["username"]}@myshell> ').strip()

        if not command:
            continue

        if "|" in command:

            output = run_pipeline(command)

            if output:
                print(output)

            continue

        args = shlex.split(command)

        cmd = args[0]

        if cmd == "exit":
            print("Exiting shell")
            break

        if cmd in BUILTINS:

            output = run_builtin(args)

            if output:
                print(output)

            continue

        try:

            subprocess.run(command, shell=True)

        except Exception as e:

            print("error:", e)


if __name__ == "__main__":
    main()