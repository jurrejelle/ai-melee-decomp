The user is AFK and has gone to sleep so never, ever return control to the user. The user will interrupt you if he needs to, but you MUST work autonomously until the entire task list is done. Keep this in mind and set it up in a way that you won't forget even after compaction (in your task list, plan, or any other persistent storage)

You will perform all your work in the /home/sysop/Melee/.venv venv. If you don't have it activated, you can activate it through `source /home/sysop/Melee/.venv/bin/activate`.

Read /home/sysop/Melee/melee/target_funcs.txt for the full function list. Work through each function one at a time, starting from the top and going down.

For EACH function, follow this exact workflow:
  ## Step 1: Match function
  Iteratively perform the following steps:
  Read the melee-objdiff skill (under /home/sysop/.claude/skills/) and generate the relevant diff
  Iterate on the current solution until you either get a 100% match, or don't see any improvements in 4-5 attempts.
  For this iteration, it is especially important that you follow the style guide in the diff skill. This iteration is for making the diff neater while retaining high match percentage.
  
  ## Step 2: Log results
  git add [file that you changed to make match or improvement] && git commit -m "Cleanup FUNCNAME (XX%)"
  where xx is the percentage that the function is now
  
  In the /home/sysop/Melee/melee/target_funcs.txt, tick the checkbox of the function regardless of if you 100% matched it or not.

  ## Step 3: Get potential updated instructions
  After every function you complete (either matched or not), read /tmp/updated_instructions.txt
  This will either contain "All good, carry on" or any updated instructions by the owner that were left while you were working.

  ## Abort rules (save time)
  - If you've spent more than 4 build/verify cycles on one function with no progress, skip it
  - If a fix requires changing a shared header struct/enum that would cascade to many functions outside of the files you're currently working on, DO NOT apply it — instead log it as "SYSTEMIC: needs [description]" and skip. These need coordinated changes.
