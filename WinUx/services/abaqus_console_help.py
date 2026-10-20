"""Local English quick reference for Abaqus commands on Linux."""

ABAQUS_LINUX_HELP = """WinUx SSH Console - Abaqus on Linux
==================================
Type --help to display this quick reference.
Replace abaqus with your site's launcher (for example, abq2024) if needed.
Replace model, model.inp and model.odb with your own job/file names.

1. Check the host and Abaqus installation
   hostname -f
       Show the Linux host you are connected to.
   command -v abaqus
       Locate the Abaqus launcher on PATH.
   abaqus information=release
       Show the installed Abaqus release.
   abaqus information=system
       Show system information for the current host.
   abaqus information=environment
       Show the effective Abaqus environment settings.

2. Check license usage
   abaqus licensing ru
       Report license usage from the configured license server, including
       users/hosts where provided by the license backend.
   hostname -s
       Show the short name of the current host for comparison with the report.
   abaqus licensing ru | grep -i "$(hostname -s)"
       Filter the report for this host. Host naming/report formats can differ;
       use the unfiltered report if the filter returns no matches.
       The license server may be a different host from the analysis host.
       License utilities depend on the site's FLEXnet or DSLS configuration.

3. Run an analysis from an input file
   cd /path/to/working/directory
   abaqus job=model input=model.inp cpus=8 interactive
       Run the analysis in the foreground using 8 CPUs.
   abaqus job=model input=model.inp cpus=8
       Submit the analysis using Abaqus's default background execution mode.
   abaqus job=model_check input=model.inp datacheck interactive
       Check the model/input without running the full analysis.

   Run a job with a dedicated scratch directory:
   mkdir -p /path/to/scratch/model
   cd /path/to/working/directory
   abaqus job=model input=model.inp cpus=8 scratch=/path/to/scratch/model interactive
       Write temporary solver files under the specified scratch directory.
       The scratch directory must already exist and be writable by your user.
       Job output files (.odb, .sta, .msg, .dat, .log) stay in the working directory.

   Keep job output and scratch under one folder:
   mkdir -p /path/to/job_folder
   cd /path/to/job_folder
   abaqus job=model input=/path/to/model.inp cpus=8 scratch="$PWD" interactive
       Run from job_folder so output files are written there, and use the same
       folder as the scratch root. Abaqus may create temporary subdirectories
       inside it and normally removes scratch files after successful completion.
       Use an absolute input path if the .inp file is outside job_folder.
       Remove interactive from either example for default background execution.
       On a managed cluster, use the site's scheduler submission procedure.

4. Monitor analysis output
   tail -n 50 model.sta
       Read the most recent analysis status lines.
   tail -f model.sta
       Follow new status lines; Ctrl+C stops tail, not the Abaqus analysis.
   tail -n 50 model.msg
       Inspect solver messages when a .msg file is available.
   tail -n 50 model.dat
       Inspect printed output, warnings and errors.
   tail -n 50 model.log
       Inspect the job execution log.

5. Control a running analysis
   abaqus job=model suspend
       Suspend an analysis that supports suspend/resume.
   abaqus job=model resume
       Resume a suspended analysis.
   abaqus job=model terminate
       Request termination of the named analysis.
       Use the correct working directory and job name.

6. Run Python scripts and postprocessing
   abaqus python script.py
       Run a script with the Abaqus Python interpreter (for example, odbAccess).
   abaqus cae noGUI=postprocess.py -- model.odb
       Run a CAE script without the GUI; arguments after -- go to the script.
   abaqus viewer database=model.odb
       Open an ODB in Viewer; requires a graphical display/X forwarding.

7. SLURM commands, if your cluster uses SLURM
   sbatch submit.sh
       Submit the site's Abaqus batch script.
   squeue -u "$USER"
       List your queued and running jobs.
   scancel JOB_ID
       Cancel a scheduler job by its SLURM job ID.
       A scheduler job ID is different from an Abaqus job name.

Console shortcuts
   Enter          Submit the current command.
   Up / Down      Recall command history.
   Left / Right   Move within the current command.
   Home / End     Move to the beginning/end of the command.
   Ctrl+V         Paste text into the command line.
   Ctrl+C         Copy selected text; without a selection, send an interrupt.
   Ctrl+F         Search the console output.

This help is displayed locally; it does not execute commands on the server.
"""
