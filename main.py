import discord
from discord.ext import commands
import json
import datetime
import os
import subprocess
import shutil
import signal
import sys
import platform
import time

OWNER_ID = 1252377453343543317  # Mets ici ton vrai ID Discord
BOTS_FILE = "bots_gestion.json" # ne pas toucher (db du bot de gestion)
CLIENT_SCRIPT = "client_template.py" # mettre le script dans ce fichier (template du bot client)
ROOT_CLIENTS = "clients_bots" # role ajouté aux clients lors de la création du bot client 
ROLE_PREFIX = "ClientBot" # sah ca on s'en blc

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="+", intents=intents)
bot.remove_command("help")

def load_bots():
    try:
        with open(BOTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_bots(bots):
    with open(BOTS_FILE, "w", encoding="utf-8") as f:
        json.dump(bots, f, ensure_ascii=False, indent=2)

def get_remaining_days(expiry_str):
    expiry_date = datetime.datetime.strptime(expiry_str, "%Y-%m-%d %H:%M:%S")
    now = datetime.datetime.utcnow()
    delta = expiry_date - now
    return max(delta.days, 0), delta

def owner_only():
    async def predicate(ctx):
        return ctx.author.id == OWNER_ID
    return commands.check(predicate)

def launch_bot(folder):
    kwargs = dict(cwd=folder)
    if platform.system().lower() == "windows":
        kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
        proc = subprocess.Popen([sys.executable, "botclient.py"], **kwargs)
    else:
        kwargs['preexec_fn'] = os.setsid
        proc = subprocess.Popen([sys.executable, "botclient.py"], **kwargs)
    with open(os.path.join(folder, "pid.txt"), "w") as f:
        f.write(str(proc.pid))
    return proc.pid

def create_bot_client(token, expiry_date, bot_id):
    os.makedirs(ROOT_CLIENTS, exist_ok=True)
    folder = os.path.join(ROOT_CLIENTS, f"bot_{bot_id}")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "settings.json"), "w", encoding="utf-8") as f:
        json.dump({}, f, ensure_ascii=False, indent=2)
    with open(CLIENT_SCRIPT, "r", encoding="utf-8") as f:
        code = f.read()
    code = code.replace("TOKENCLIENT", token)
    code = code.replace("#EXPIRY", f'EXPIRY_DATE = "{expiry_date}"')
    script_path = os.path.join(folder, "botclient.py")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(code)
    launch_bot(folder)
    return folder

def kill_pid_file(folder):
    pid_file = os.path.join(folder, "pid.txt")
    if not os.path.exists(pid_file):
        return False
    try:
        with open(pid_file, "r") as f:
            pid = int(f.read().strip())
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return True
        for _ in range(10):
            time.sleep(0.2)
            try:
                os.kill(pid, 0)
            except OSError:
                return True
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
        return True
    except Exception:
        return False

async def give_client_role(guild, user: discord.Member, bot_id: int):
    role_name = f"{ROLE_PREFIX}_{bot_id}"
    role = discord.utils.get(guild.roles, name=role_name)
    if role is None:
        role = await guild.create_role(name=role_name, mentionable=True, reason="Rôle client bot automatique")
    await user.add_roles(role)

@bot.command()
@owner_only()
async def ajoutbot(ctx, acheteur: discord.User, bot_token: str, jours: int = 30):
    bots = load_bots()
    now = datetime.datetime.utcnow()
    expiry = now + datetime.timedelta(days=jours)
    bot_id = len(bots) + 1
    folder = create_bot_client(bot_token, expiry.strftime("%Y-%m-%d %H:%M:%S"), bot_id)
    bots.append({
        "id": bot_id,
        "acheteur_id": acheteur.id,
        "acheteur_name": str(acheteur),
        "token": bot_token,
        "ajoute_le": now.strftime("%Y-%m-%d %H:%M:%S"),
        "expire_le": expiry.strftime("%Y-%m-%d %H:%M:%S"),
        "active": True,
        "folder": folder
    })
    save_bots(bots)
    member = ctx.guild.get_member(acheteur.id)
    embed = discord.Embed(
        title="🟢・Bot Client Créé",
        description=f"Le bot a été lancé pour {acheteur.mention}.\n"
                    f"**Expiration :** `{expiry.strftime('%Y-%m-%d %H:%M:%S')}`\n",
        color=0x2ecc71
    )
    if member is not None:
        await give_client_role(ctx.guild, member, bot_id)
        role = discord.utils.get(ctx.guild.roles, name=f"{ROLE_PREFIX}_{bot_id}")
        embed.add_field(name="Rôle attribué", value=f"{role.mention if role else 'Rôle non trouvé'}", inline=False)
    else:
        embed.add_field(name="Attention", value="Impossible d'attribuer le rôle car l'utilisateur n'est pas sur ce serveur.", inline=False)
    embed.set_footer(text=f"Easy-bots • Prefix +")
    await ctx.send(embed=embed)

@bot.command()
@owner_only()
async def supprbot(ctx, bot_id: int):
    bots = load_bots()
    botinfo = next((b for b in bots if b["id"] == bot_id), None)
    embed = discord.Embed(
        title="❌・Suppression du Bot Client",
        color=0xe74c3c
    )
    if not botinfo:
        embed.description = f"Aucun bot avec l'ID `{bot_id}`."
        await ctx.send(embed=embed)
        return
    folder = botinfo.get("folder")
    killed = False
    if folder and os.path.exists(folder):
        killed = kill_pid_file(folder)
        try:
            shutil.rmtree(folder)
        except Exception:
            pass
    member = ctx.guild.get_member(botinfo["acheteur_id"])
    role_name = f"{ROLE_PREFIX}_{bot_id}"
    role = discord.utils.get(ctx.guild.roles, name=role_name)
    if member and role:
        try:
            await member.remove_roles(role)
        except Exception:
            pass
    if role:
        try:
            await role.delete(reason="Bot client supprimé")
        except Exception:
            pass
    bots = [b for b in bots if b["id"] != bot_id]
    save_bots(bots)
    embed.description = f"Bot ID `{bot_id}` supprimé.\n{'Process tué.' if killed else 'Dossier supprimé.'}"
    embed.set_footer(text="Easy-bots • Prefix +")
    await ctx.send(embed=embed)

@bot.command()
async def tempsrestant(ctx):
    bots = load_bots()
    user_bots = [b for b in bots if b["acheteur_id"] == ctx.author.id]
    if not user_bots:
        embed = discord.Embed(
            title="⏳・Temps Restant",
            description="❌・Tu n'as pas de bot actif associé à ton compte.",
            color=0xe74c3c
        )
        embed.set_footer(text="Easy-bots • Prefix +")
        await ctx.send(embed=embed)
        return
    embed = discord.Embed(
        title="⏳ Temps restant d'utilisation",
        color=0x2ecc71
    )
    for b in user_bots:
        days, delta = get_remaining_days(b["expire_le"])
        status = "🟢・Actif" if b["active"] and days > 0 else "🔴・Expiré"
        role_name = f"{ROLE_PREFIX}_{b['id']}"
        role = discord.utils.get(ctx.guild.roles, name=role_name)
        embed.add_field(
            name=f"Bot ID `{b['id']}` {role.mention if role else role_name}",
            value=f"Statut : {status}\nExpire dans **{days} jours**\nExpire le : `{b['expire_le']}`",
            inline=False
        )
    embed.set_footer(text="Easy-bots • Prefix +")
    await ctx.send(embed=embed)

@bot.command()
@owner_only()
async def expiration(ctx):
    bots = load_bots()
    embed = discord.Embed(
        title="📋 Liste des bots revendus",
        color=0x3498db
    )
    if not bots:
        embed.description = "Aucun bot enregistré."
        await ctx.send(embed=embed)
        return
    for b in bots:
        days, delta = get_remaining_days(b['expire_le'])
        status = "🟢 Actif" if b['active'] and days > 0 else "🔴 Expiré"
        embed.add_field(
            name=f"ID: {b['id']} | {b['acheteur_name']} | {status}",
            value=f"Expire dans {days} jours\nExpire le: {b['expire_le']}\nToken: `{b['token'][:7]}...`",
            inline=False
        )
    embed.set_footer(text="Easy-bots • Prefix +")
    await ctx.send(embed=embed)

@bot.command()
@owner_only()
async def listebots(ctx):
    bots = load_bots()
    embed = discord.Embed(
        title="📋 Liste de tous les bots & clients",
        color=0x3498db
    )
    if not bots:
        embed.description = "Aucun bot trouvé."
        await ctx.send(embed=embed)
        return
    descr = ""
    for b in bots:
        descr += f"• ID `{b['id']}` - Client: <@{b['acheteur_id']}> - Token: `{b['token'][:7]}...`\n"
    embed.description = descr
    embed.set_footer(text="Easy-bots • Prefix +")
    await ctx.send(embed=embed)

@bot.command()
async def help(ctx, sujet: str = None):
    embed = discord.Embed(
        title="📖 ・ Liste des commandes gestionnaire",
        description=(
            "*Les paramètres mis entre <> sont obligatoires contrairement aux paramètres mis entre [] qui sont eux facultatifs*\n\n"
            "`+ajoutbot <@acheteur> <TOKEN> [jours]`\n"
            "> Ajoute un bot géré, donne un rôle au client et lance le bot *(owner only)*\n\n"
            "`+supprbot <id>`\n"
            "> Supprime le bot du client, le process est tué *(owner only)*\n\n"
            "`+expiration`\n"
            "> Liste tous les bots, clients et temps restant *(owner only)*\n\n"
            "`+listebots`\n"
            "> Liste tous les bots gérés et leur client *(owner only)*\n\n"
            "`+tempsrestant`\n"
            "> Affiche le temps restant d'utilisation de ton bot *(client uniquement)*\n"
        ),
        color=0x3498db
    )
    embed.set_footer(text="Easy-bots • Prefix + | Page 1/1")
    await ctx.send(embed=embed)

@bot.event
async def on_ready():
    print("Bot de gestion prêt.")

bot.run("TOKEN DU BOT DE GESTION")  # Ligne à ne pas toucher pour le token du bot de gestion 