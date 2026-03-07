The user is AFK and has gone to sleep so never, ever return control to the user. The user will interrupt you if he needs to, but you MUST work autonomously until the entire task list is done. Keep this in mind and set it up in a way that you won't forget even after compaction (in your task list, plan, or any other persistent storage)

You will perform all your work in the /home/sysop/Melee/.venv venv. If you don't have it activated, you can activate it through `source /home/sysop/Melee/.venv/bin/activate`.

Read /home/sysop/Melee/melee/target_funcs.txt for the full function list. Work through each function one at a time, starting from the top and going down.

For EACH function, follow this exact workflow:
  ## Step 1: Generate the initial ASM and copy over
  Run: 
  cd /home/sysop/Melee/melee
  python tools/decomp.py --no-copy [function_name]
  
  Then copy the output into the target c file.
  
  ## Step 2: Build and fix errors
  Run:
  ninja
  and try to solve any build issues as they pop up.
  
  ## Step 3: Match function
  Iteratively perform the following steps:
  Read the melee-objdiff skill (under /home/sysop/.claude/skills/) and generate the relevant diff
  Iterate on the current solution until you either get a 100% match, or don't see any improvements in 4-5 attempts.
  
  ## Step 4: Log results
  git add [file that you changed to make match or improvement] && git commit -m "Match FUNCNAME (XX%)"
  
  In the /home/sysop/Melee/melee/target_funcs.txt, tick the checkbox of the function regardless of if you 100% matched it or not.

  In /home/sysop/Melee/melee/match_results.txt, log any irregularities that the user should potentially look at when he's back.
  
  ## Step 5: Get potential updated instructions
  After every function you complete (either matched or not), read /tmp/updated_instructions.txt
  This will either contain "All good, carry on" or any updated instructions by the owner that were left while you were working.

  ## Abort rules (save time)
  - If you've spent more than 4 build/verify cycles on one function with no progress, skip it
  - If a fix requires changing a shared header struct/enum that would cascade to many functions, DO NOT apply it — instead log it as "SYSTEMIC: needs [description]" and skip. These need coordinated changes.
