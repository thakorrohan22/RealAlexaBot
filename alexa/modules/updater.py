# Copyright (C) 2019 The Raphielscape Company LLC.
#
# Licensed under the Raphielscape Public License, Version 1.c (the "License");
# you may not use this file except in compliance with the License.
#
"""
This module updates the alexa based on Upstream revision
"""
import asyncio
import sys
from os import environ
from os import execle
from os import getenv
from os import makedirs
from os import path
from os import remove
from shutil import rmtree

from git import Repo
from git.exc import GitCommandError
from git.exc import InvalidGitRepositoryError
from git.exc import NoSuchPathError

from alexa import HEROKU_APIKEY
from alexa import HEROKU_APPNAME
from alexa import UPSTREAM_REPO_URL
from alexa import OWNER_ID
from alexa.events import register

requirements_path = path.join(
    path.dirname(path.dirname(path.dirname(__file__))), "requirements.txt")


async def gen_chlog(repo, diff):
    ch_log = ""
    d_form = "%d/%m/%y"
    for c in repo.iter_commits(diff):
        ch_log += (
            f"•[{c.committed_datetime.strftime(d_form)}]: {c.summary} <{c.author}>\n"
        )
    return ch_log


async def update_requirements():
    reqs = str(requirements_path)
    try:
        process = await asyncio.create_subprocess_shell(
            " ".join([sys.executable, "-m", "pip", "install", "-r", reqs]),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await process.communicate()
        return process.returncode
    except Exception as e:
        return repr(e)


@register(pattern="^/update(?: |$)(.*)")
async def upstream(ups):
  check = ups.message.sender_id
  checkint = int(check)
  print(checkint)
  if int(check) != int(OWNER_ID):
       return
  else:
    "For .update command, check if the bot is up to date, update if specified"
    lol = await ups.reply("`Checking for updates, please wait....`")
    conf = ups.pattern_match.group(1)
    off_repo = UPSTREAM_REPO_URL
    force_update = False

    try:
        txt = "`Oops.. Updater cannot continue due to "
        txt += "some problems occured`\n\n**LOGTRACE:**\n"
        repo = Repo()
    except NoSuchPathError as error:
        await lol.edit(f"{txt}\n`directory {error} is not found`")
        repo.__del__()
        return
    except GitCommandError as error:
        await lol.edit(f"{txt}\n`Early failure! {error}`")
        repo.__del__()
        return
    except InvalidGitRepositoryError as error:
        if conf != "now":
            await lol.edit(
                f"`Unfortunately, the directory {error} does not seem to be a git repository.\
            \nBut we can fix that by force updating the alexa using /update now.`"
            )
            return
        repo = Repo.init()
        origin = repo.create_remote("upstream", off_repo)
        origin.fetch()
        force_update = True
        repo.create_head("stable", origin.refs.stable)
        repo.heads.stable.set_tracking_branch(origin.refs.stable)
        repo.heads.stable.checkout(True)

    ac_br = repo.active_branch.name
    if ac_br != "stable":
        await lol.edit(
            f"**[UPDATER]:**` Looks like you are using your own custom branch ({ac_br}). "
            "in that case, Updater is unable to identify "
            "which branch is to be merged. "
            "please checkout to any official branch`")
        repo.__del__()
        return

    try:
        repo.create_remote("upstream", off_repo)
    except BaseException:
        pass

    ups_rem = repo.remote("upstream")
    ups_rem.fetch(ac_br)

    changelog = await gen_chlog(repo, f"HEAD..upstream/{ac_br}")

    if not changelog and not force_update:
        await lol.edit(
            f"\n`Your BOT is`  **up-to-date**  `with`  **{ac_br}**\n")
        repo.__del__()
        return

    if conf != "now" and not force_update:
        changelog_str = (
            f"**New UPDATE available for [{ac_br}]:\n\nCHANGELOG:**\n`{changelog}`"
        )
        if len(changelog_str) > 4096:
            await lol.edit("`Changelog is too big, view the file to see it.`")
            file = open("output.txt", "w+")
            file.write(changelog_str)
            file.close()
            await ups.client.send_file(
                ups.chat_id,
                "output.txt",
                reply_to=ups.id,
            )
            remove("output.txt")
        else:
            await lol.edit(changelog_str)
        await ups.respond('`do "/update now" to update`')
        return

    if force_update:
        await lol.edit(
            "`Force-Syncing to latest stable alexa code, please wait...`")
    else:
        await lol.edit("`Updating alexa, please wait....`")
    # We're in a Heroku Dyno, handle it's memez.
    if HEROKU_APIKEY is not None:
        import heroku3

        heroku = heroku3.from_key(HEROKU_APIKEY)
        heroku_app = None
        heroku_applications = heroku.apps()
        if not HEROKU_APPNAME:
            await lol.edit(
                "`[HEROKU DYNOS] Please set up the HEROKU_APPNAME variable to be able to update alexa.`"
            )
            repo.__del__()
            return
        for app in heroku_applications:
            if app.name == HEROKU_APPNAME:
                heroku_app = app
                break
        if heroku_app is None:
            await lol.edit(
                f"{txt}\n`Invalid Heroku credentials for updating alexa dyno.`"
            )
            repo.__del__()
            return
        await lol.edit("`[HEROKU DYNOS]\
                        \nalexa dyno build in progress, please wait for it to complete.`"
                       )
        ups_rem.fetch(ac_br)
        repo.git.reset("--hard", "FETCH_HEAD")
        heroku_git_url = heroku_app.git_url.replace(
            "https://", "https://api:" + HEROKU_APIKEY + "@")
        if "heroku" in repo.remotes:
            remote = repo.remote("heroku")
            remote.set_url(heroku_git_url)
        else:
            remote = repo.create_remote("heroku", heroku_git_url)
        try:
            remote.push(refspec="HEAD:refs/heads/stable", force=True)
        except GitCommandError as error:
            await lol.edit(f"{txt}\n`Here is the error log:\n{error}`")
            repo.__del__()
            return
        await lol.edit("`Successfully Updated!\n"
                       "Restarting, please wait...`")
    else:
        # Classic Updater, pretty straightforward.
        try:
            ups_rem.pull(ac_br)
        except GitCommandError:
            repo.git.reset("--hard", "FETCH_HEAD")
        reqs_upgrade = await update_requirements()
        await lol.edit("`Successfully Updated!\n"
                       "Bot is restarting... Wait for a second!`")
        # Spin a new instance of bot
        args = [sys.executable, "-m", "alexa"]
        execle(sys.executable, *args, environ)
        return
