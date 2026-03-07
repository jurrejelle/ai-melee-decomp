This repo serves two functions. The first is for me to document my own setup incase I want to copy it to another machine. The second is to serve as a guide for others who want to use AI for melee decomp.

Notes:
- This guide will assume you have a clean VM with a user called sysop. Make sure to change the paths for yourself in the files
- What you want to gitignore depends on your repo. To edit your personal gitignore, change `.git/info/exclude` in your git repo.
How to setup AI-based decomp for melee:
## Setting up melee-decomp without AI relevant stuff
1. Clone your melee fork (/home/sysop/Melee/melee for me)
2. Create a venv (`python3 -m venv /home/sysop/Melee/.venv`)
3. `source /home/sysop/Melee/.venv/bin/activate`
4. `for i in \`melee/reqs/*.txt\`; do pip3 install -r $i; done`
5. `apt install ninja-build`
5. `mkdir objdiffs`
6. `wget https://github.com/encounter/objdiff/releases/download/v3.6.1/objdiff-cli-linux-x86_64 -o objdiffs/`
7. `sudo ln -s /home/sysop/Melee/objdiffs/objdiff-cli-linux-x86_64 /bin/objdiff`
8. Copy your main.dol into Melee/melee/orig/GALE01/sys
9. in melee: `python3 configure.py`; `ninja build`

## AI specific stuff
For this guide we will be requestmaxxing using copilot's request system and opus 4.6. It's also posssible to do this with claude code, pi.dev, etc
1. `sudo npm install -g @github/copilot` 
2. login with your github account. this will require copilot pro.
3. copy the `skills` directory into /home/sysop/.claude/
4. (optional) change the paths mentioned in the objdiff_wrapper.py
5. copy the AUTO_CLAUDE.md into your repo, change these steps for your project but it should follow the same format


## For every session
1. Create a new branch for it to work on
2. Optionally, run `tools/scaffold.py` and make sure the scaffolds are correct for your function
3. Get a list of functions using `python3 tools/easy_funcs.py [target file] -n 1000 -S 10000 -M 99.99`
4. Put the list of functions in a checkbox format in a "target_functions.txt" file 
5. Create an empty /tmp/updated_instructions.txt file
6. Run `screen -R decomp`. This will open a screen so the bot will continue even when you leave
7. Run `copilot`
8. Run `/yolo` to disable questions.
9. With /model, swap to opus 4.6 high
10. Tell it "Read AUTO_CLAUDE.md. You will be working on [target file here]. I am going to sleep, do not ever ask me anything or return control to me"."
11. Press ctrl+a + d, this will detatch from the screen. You can now leave if you want
12. To re-attach, `screen -r decomp`

