import asyncio
from http.client import HTTPException
import os
import sys
import zipfile
import shutil
from pathlib import Path

import aiohttp
import aiofiles
from dotenv import load_dotenv
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QTextEdit,
    QPushButton,
    QLabel,
    QProgressBar,
)
from PyQt5.QtCore import pyqtSignal, QObject, QThread


def copy_pack_incremental(src: Path, dest: Path, progress_callback=None):
    """Copie le contenu de src vers dest sans supprimer les fichiers déjà existants."""
    files = list(src.rglob("*"))
    total_files = len([f for f in files if f.is_file()])
    copied_files = 0

    for root, dirs, file_names in os.walk(src):
        rel_path = Path(root).relative_to(src)
        target_dir = dest / rel_path
        target_dir.mkdir(parents=True, exist_ok=True)

        for file in file_names:
            shutil.copy2(Path(root) / file, target_dir / file)
            copied_files += 1
            if progress_callback:
                progress_callback(int((copied_files / total_files) * 100))


APP_NAME = "RLCraftInstaller"


def get_version_file_path() -> Path:
    """Retourne le chemin du fichier .version, hors de l'exécutable PyInstaller."""
    if getattr(sys, "frozen", False):  # Mode PyInstaller
        # Sous Windows → %APPDATA%\RLCraftInstaller\.version
        appdata_dir = Path(os.getenv("APPDATA", Path.home()))
        config_dir = appdata_dir / APP_NAME
    else:
        # En mode dev → même dossier que le script
        config_dir = Path(__file__).parent

    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / ".version"


VERSION_FILE = get_version_file_path()
downloaded = False
errors = None


def get_script_dir():
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


class Logger(QObject):
    log_signal = pyqtSignal(str)

    def log(self, message):
        self.log_signal.emit(message)


logger = Logger()


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RLCraft Bedrock Installer")
        self.resize(600, 500)

        layout = QVBoxLayout()
        self.label = QLabel("RLCraft Bedrock Installer")
        self.text_edit = QTextEdit(readOnly=True)

        self.progress_download = QProgressBar()
        self.progress_install = QProgressBar()
        self.progress_download.setValue(0)
        self.progress_install.setValue(0)

        self.button_start = QPushButton("Démarrer l'installation")
        self.button_close = QPushButton("Fermer")
        self.button_close.setEnabled(False)

        layout.addWidget(self.label)
        layout.addWidget(self.text_edit)
        layout.addWidget(QLabel("Téléchargement :"))
        layout.addWidget(self.progress_download)
        layout.addWidget(QLabel("Installation :"))
        layout.addWidget(self.progress_install)
        layout.addWidget(self.button_start)
        layout.addWidget(self.button_close)

        self.setLayout(layout)

        logger.log_signal.connect(self.append_log)
        self.button_start.clicked.connect(self.start_install)
        self.button_close.clicked.connect(self.close)

    def append_log(self, message):
        self.text_edit.append(message)

    def start_install(self):
        self.button_start.setEnabled(False)
        self.thread = QThread()
        self.worker = InstallerWorker()
        self.worker.moveToThread(self.thread)

        # Connexions
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        if downloaded:
            self.worker.finished.connect(self.install_done)
        else:
            self.button_close.setEnabled(True)
        self.worker.download_progress.connect(self.progress_download.setValue)
        self.worker.copy_progress.connect(self.progress_install.setValue)

        self.thread.start()

    def install_done(self):
        logger.log("✅ Installation terminée !")
        self.button_close.setEnabled(True)


class InstallerWorker(QObject):
    finished = pyqtSignal()
    download_progress = pyqtSignal(int)  # en %
    copy_progress = pyqtSignal(int)  # en %

    def run(self):
        asyncio.run(self._run_async())
        self.finished.emit()

    async def _run_async(self):
        new_packs_folder = await get_rlcraft_release(self.download_progress)
        if not isinstance(new_packs_folder, Path) and not downloaded and errors:
            logger.log("Échec du téléchargement de la release.")
            return
        elif not isinstance(new_packs_folder, Path) and not downloaded:
            logger.log("Pas de nouvelles mises à jour")
            return

        # Copie des fichiers
        MC_UWP_data_folder = Path().home() / "AppData" / "Local" / "Packages"
        minecraft_folder = None
        for folder in MC_UWP_data_folder.iterdir():
            if folder.name.startswith("Microsoft.MinecraftUWP"):
                logger.log(f"Minecraft Bedrock folder found ! {folder}")
                minecraft_folder = folder / "LocalState" / "games" / "com.mojang"
                break

        if not minecraft_folder or not minecraft_folder.exists():
            logger.log("Dossier Minecraft introuvable.")
            return

        mc_data_packs_folders = ["behavior_packs", "resource_packs"]
        total_files = sum(
            len(list((new_packs_folder / f).rglob("*"))) for f in mc_data_packs_folders
        )
        copied_files = 0

        for folder_name in mc_data_packs_folders:
            old_pack = minecraft_folder / folder_name
            new_pack = new_packs_folder / folder_name
            if new_pack.exists():
                log(f"Copie de {new_pack} vers {old_pack}")
                # Ancien code (supprime tout)
                # if old_pack.exists():
                #     shutil.rmtree(old_pack)
                # shutil.copytree(new_pack, old_pack)

                # Nouveau code (merge incrémental)
                copy_pack_incremental(new_pack, old_pack, self.copy_progress.emit)

        shutil.rmtree(new_packs_folder)


def log(msg):
    logger.log(str(msg))


def unzip_rlcraft_release(release_fp: Path) -> Path:
    extract_dir = release_fp.with_suffix("")
    extract_dir.mkdir(exist_ok=True)
    with zipfile.ZipFile(release_fp, "r") as zip_ref:
        zip_ref.extractall(extract_dir)
    log(f"Fichiers extraits dans {extract_dir}")
    release_fp.unlink()
    return extract_dir


async def get_rlcraft_release(progress_signal):
    load_dotenv()
    REPO_OWNER = "Wishrito"
    REPO_NAME = "BedrockRLCraftCrack"
    GITHUB_ACCESS_TOKEN = os.getenv("GITHUB_ACCESS_TOKEN")

    api_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"
    headers = {}
    if GITHUB_ACCESS_TOKEN:
        headers["Authorization"] = f"token {GITHUB_ACCESS_TOKEN}"

    # Vérification version
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(api_url, headers=headers) as response:
                response.raise_for_status()
                release_data: dict = await response.json()
        except HTTPException as err:
            global errors
            errors = err

    tag_name = release_data.get("tag_name", "N/A")
    log(f"Dernière release : {tag_name}")

    # Lire la version locale
    if VERSION_FILE.exists():
        local_version = VERSION_FILE.read_text().strip()
    else:
        local_version = None

    global downloaded

    # Comparer avec version distante
    if local_version == tag_name:
        downloaded = False
        log("✅ Déjà à jour")
        return None

    # après installation réussie :
    downloaded = True
    VERSION_FILE.write_text(tag_name)

    assets = release_data.get("assets", [])
    if not assets:
        log("Aucun asset trouvé.")
        return None

    asset: dict = assets[0]
    filename: str = asset.get("name", "unknown.zip")
    download_url: str | None = asset.get("browser_download_url")

    if not download_url:
        log("Lien de téléchargement introuvable.")
        return None

    release_fp = Path(__file__).parent / filename
    async with aiohttp.ClientSession() as session:
        async with session.get(download_url) as file_response:
            file_response.raise_for_status()
            total_size = int(file_response.headers.get("Content-Length", 0))
            downloaded_size = 0
            async with aiofiles.open(release_fp, "wb") as f:
                async for chunk in file_response.content.iter_chunked(8192):
                    await f.write(chunk)
                    downloaded_size += len(chunk)
                    if total_size:
                        progress_signal.emit(int((downloaded_size / total_size) * 100))

    VERSION_FILE.write_text(tag_name)
    return unzip_rlcraft_release(release_fp)


if __name__ == "__main__":
    icon_path = Path(__file__).parent / "src" / "rlcraft.ico"
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(icon_path)))
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
