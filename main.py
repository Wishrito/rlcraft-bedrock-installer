import asyncio
from pathlib import Path
import zipfile

import aiohttp
import aiofiles

async def unzip_rlcraft_release(release_fp: Path):

    extract_dir = Path(release_fp.stem)
    extract_dir.mkdir()
    with zipfile.ZipFile(release_fp, "r") as zip_ref:
        zip_ref.extractall(extract_dir)

    print(f"fichiers extraits dans {extract_dir}")

async def get_rlcraft_release():
    REPO_OWNER = "Wishrito"
    REPO_NAME = "BedrockRLCraftCrack"
    api_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"
    async with aiohttp.ClientSession() as session:
        async with session.get(api_url) as response:
            response.raise_for_status()
            release_data = await response.json()

            tag_name = release_data.get("tag_name", "N/A")
            print(f"Dernière release : {tag_name}")

            assets = release_data.get("assets", [])
            if assets:
                asset = assets[0]
                filename: str = asset.get("name", "unknown")
                download_url = asset.get("browser_download_url")
                print(f"Nom de l'asset : {filename}")
                print(f"Lien de téléchargement : {download_url}")

                if download_url:
                    print(f"Téléchargement de {filename}...")
                    async with session.get(download_url) as file_response:
                        file_response.raise_for_status()
                        release_fp = Path(__file__).parent / filename
                        async with aiofiles.open(release_fp, "wb") as f:
                            while True:
                                chunk = await file_response.content.read(8192)
                                if not chunk:
                                    break
                                await f.write(chunk)
                        await unzip_rlcraft_release(release_fp)

            else:
                print("Aucun asset trouvé.")


async def main():
    await get_rlcraft_release()
    MC_UWP_data_folder = Path().home() / "AppData" / "Local" / "Packages"

    minecraft_folder: Path | None = None
    for folder in MC_UWP_data_folder.iterdir(): # boucle sur tous les dossiers de l'arborescence de fichiers 
        if folder.name.startswith("Microsoft.MinecraftUWP"):
            print(f"Minecraft Bedrock folder found ! {folder}")
            minecraft_folder = Path(folder)
            break
    minecraft_folder = Path(str(minecraft_folder)) /  "LocalState" / "games" / "com.mojang"
    mc_data_packs_folders = [minecraft_folder / "behavior_packs", minecraft_folder / "resource_packs"]
    for data_packs_folder in mc_data_packs_folders:
        pass


asyncio.run(main())
