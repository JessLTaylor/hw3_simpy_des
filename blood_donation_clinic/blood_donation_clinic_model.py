#!/usr/bin/env python
# coding: utf-8

import sys
import argparse
from datetime import datetime
import math

import pandas as pd
from numpy.random import default_rng
import simpy
from pathlib import Path


class BloodDonationClinic(object):
    def __init__(self, env, num_greeters, num_reg_staff, num_bd_tech, num_schedulers,
                 mean_interarrival_time, pct_want_appt,
                 iron_check_time_mean, iron_check_time_sd,
                 reg_time_mean,
                 blooddraw_time_mean, blooddraw_time_sd,
                 sched_time_mean, sched_time_sd,
                 obs_time, post_obs_time_mean, rg
                 ):
        """
        Primary class that encapsulates clinic resources.

        The detailed patient flow logic is in get_blooddraw() function.

        Parameters
        ----------
        env
        num_greeters
        num_reg_staff
        num_bd_tech
        num_schedulers
        mean_interarrival_time
        pct_want_appt
        iron_check_time_mean
        iron_check_time_sd
        reg_time_mean
        blooddraw_time_mean
        blooddraw_time_sd
        sched_time_mean
        sched_time_sd
        obs_time
        post_obs_time_mean
        rg
        """

        # Simulation environment and random number generator
        self.env = env
        self.rg = rg

        # Create list to hold timestamps dictionaries (one per patient)
        self.timestamps_list = []
        # Create lists to hold occupancy tuples (time, occ)
        self.postbd_occupancy_list = [(0.0, 0.0)]
        self.bd_occupancy_list = [(0.0, 0.0)]

        # Create SimPy resources
        self.greeter = simpy.Resource(env, num_greeters)
        self.reg_staff = simpy.Resource(env, num_reg_staff)
        self.bd_tech = simpy.Resource(env, num_bd_tech)
        self.scheduler = simpy.Resource(env, num_schedulers)

        # Initialize the patient flow related attributes
        self.mean_interarrival_time = mean_interarrival_time
        self.pct_want_appt = pct_want_appt

        self.iron_check_time_mean = iron_check_time_mean
        self.iron_check_time_sd = iron_check_time_sd
        self.reg_time_mean = reg_time_mean
        self.blooddraw_time_mean = blooddraw_time_mean
        self.blooddraw_time_sd = blooddraw_time_sd
        self.sched_time_mean = sched_time_mean
        self.sched_time_sd = sched_time_sd
        self.obs_time = obs_time
        self.post_obs_time_mean = post_obs_time_mean

    # Create process methods
    def iron_check(self):
        yield self.env.timeout(self.rg.normal(self.iron_check_time_mean, self.iron_check_time_sd))

    def registration(self):
        yield self.env.timeout(self.rg.exponential(self.reg_time_mean))

    def blooddraw(self):
        yield self.env.timeout(self.rg.normal(self.blooddraw_time_mean, self.blooddraw_time_sd))

    def schedule_next_donation(self):
        yield self.env.timeout(self.rg.normal(self.sched_time_mean, self.sched_time_sd))

    # We assume all patients wait at least obs_time minutes post-blooddraw
    # Some will choose to wait longer. This is the time beyond obs_time minutes
    # that patients wait.
    def wait_gt_obs_time(self):
        yield self.env.timeout(self.rg.exponential(self.post_obs_time_mean))


def get_blooddraw(env, patient, clinic, quiet):
    """Defines the sequence of steps traversed by patients.

       Also capture a bunch of timestamps to make it easy to compute various system
       performance measures such as patient waiting times, queue sizes and resource utilization.
    """
    # Patient arrives to clinic - note the arrival time
    arrival_ts = env.now

    # Request a greeter for iron check
    # By using request() in a context manager, we'll automatically release the resource when done
    with clinic.greeter.request() as request:
        yield request
        # Now that we have a greeter, check iron level. Note time.
        got_greeter_ts = env.now
        yield env.process(clinic.iron_check())
        release_greeter_ts = env.now

    # Request reg staff to get registered
    with clinic.reg_staff.request() as request:
        yield request
        got_reg_ts = env.now
        yield env.process(clinic.registration())
        release_reg_ts = env.now

    # Request clinical staff to start blood donation
    with clinic.bd_tech.request() as request:
        if not quiet:
            print(f"Patient {patient} requests blood draw technician at time {env.now}")
        yield request
        got_blooddraw_ts = env.now
        q_time = got_blooddraw_ts - release_reg_ts
        if not quiet:
            print(f"Patient {patient} gets blood draw at time {env.now} (waited {q_time:.1f} minutes)")
        # Update bd occupancy - increment by 1
        prev_occ = clinic.bd_occupancy_list[-1][1]
        new_occ = (env.now, prev_occ + 1)
        clinic.bd_occupancy_list.append(new_occ)
        yield env.process(clinic.blooddraw())
        release_bd_tech_ts = env.now
        if not quiet:
            print(f"Patient {patient} releases blood draw technician at time {env.now}")
        # Update bd occupancy - decrement by 1 - more compact code
        clinic.bd_occupancy_list.append((env.now, clinic.bd_occupancy_list[-1][1] - 1))

        # Update postbd occupancy - increment by 1
        clinic.postbd_occupancy_list.append((env.now, clinic.postbd_occupancy_list[-1][1] + 1))

    # Request scheduler to schedule second dose if needed
    if clinic.rg.random() < clinic.pct_want_appt:
        with clinic.scheduler.request() as request:
            yield request
            got_scheduler_ts = env.now
            yield env.process(clinic.schedule_next_donation())
            release_scheduler_ts = env.now
    else:
        got_scheduler_ts = pd.NA
        release_scheduler_ts = pd.NA

    # Wait at least obs_time minutes from time we finished blood draw donation
    post_bd_time = env.now - release_bd_tech_ts
    if post_bd_time < clinic.obs_time:
        # Wait until 15 total minutes post blood draw donation
        yield env.timeout(clinic.obs_time - post_bd_time)
        # Wait random amount beyond obs_time minutes
        yield env.process(clinic.wait_gt_obs_time())

        # Update postbd occupancy - decrement by 1
        clinic.postbd_occupancy_list.append((env.now, clinic.postbd_occupancy_list[-1][1] - 1))

    exit_system_ts = env.now
    if not quiet:
        print(f"Patient {patient} exited system at time {env.now}")

    # Create dictionary of timestamps
    timestamps = {'patient_id': patient,
                  'arrival_ts': arrival_ts,
                  'got_greeter_ts': got_greeter_ts,
                  'release_greeter_ts': release_greeter_ts,
                  'got_reg_ts': got_reg_ts,
                  'release_reg_ts': release_reg_ts,
                  'got_blooddraw_ts': got_blooddraw_ts,
                  'release_bd_tech_ts': release_bd_tech_ts,
                  'got_scheduler_ts': got_scheduler_ts,
                  'release_scheduler_ts': release_scheduler_ts,
                  'exit_system_ts': exit_system_ts}

    clinic.timestamps_list.append(timestamps)


def run_clinic(env, clinic, stoptime=simpy.core.Infinity, max_arrivals=simpy.core.Infinity, quiet=False):
    """
    Run the clinic for a specified amount of time or after generating a maximum number of patients.

    Parameters
    ----------
    env : SimPy environment
    clinic : ``BloodDonationClinic`` object
    stoptime : float
    max_arrivals : int
    quiet : bool

    Yields
    -------
    Simpy environment timeout
    """

    # Create a counter to keep track of number of patients generated and to serve as unique patient id
    patient = 0

    # Loop for generating patients
    while env.now < stoptime and patient < max_arrivals:
        # Generate next interarrival time (this will be more complicated later)
        iat = clinic.rg.exponential(clinic.mean_interarrival_time)

        # This process will now yield to a 'timeout' event. This process will resume after iat time units.
        yield env.timeout(iat)

        # New patient generated = update counter of patients
        patient += 1

        if not quiet:
            print(f"Patient {patient} created at time {env.now}")

        # Register a get_blooddraw process for the new patient
        env.process(get_blooddraw(env, patient, clinic, quiet))

    print(f"{patient} patients processed.")


def compute_durations(timestamp_df):
    """Compute time durations of interest from timestamps dataframe and append new cols to dataframe"""

    timestamp_df['wait_for_greeter'] = timestamp_df.loc[:, 'got_greeter_ts'] - timestamp_df.loc[:, 'arrival_ts']
    timestamp_df['wait_for_reg'] = timestamp_df.loc[:, 'got_reg_ts'] - timestamp_df.loc[:, 'release_greeter_ts']
    timestamp_df['wait_for_bd_tech'] = timestamp_df.loc[:, 'got_blooddraw_ts'] - timestamp_df.loc[:,
                                                                                     'release_reg_ts']
    timestamp_df['blooddraw_time'] = timestamp_df.loc[:, 'release_bd_tech_ts'] - timestamp_df.loc[:,
                                                                                      'got_blooddraw_ts']
    timestamp_df['wait_for_scheduler'] = timestamp_df.loc[:, 'got_scheduler_ts'] - timestamp_df.loc[:,
                                                                                   'release_bd_tech_ts']
    timestamp_df['post_bdd_time'] = timestamp_df.loc[:, 'exit_system_ts'] - timestamp_df.loc[:,
                                                                             'release_bd_tech_ts']
    timestamp_df['time_in_system'] = timestamp_df.loc[:, 'exit_system_ts'] - timestamp_df.loc[:, 'arrival_ts']

    return timestamp_df


def simulate(arg_dict, rep_num):
    """

    Parameters
    ----------
    arg_dict : dict whose keys are the input args
    rep_num : int, simulation replication number

    Returns
    -------
    Nothing returned but numerous output files written to ``args_dict[output_path]``

    """

    # Create a random number generator for this replication
    seed = arg_dict['seed'] + rep_num - 1
    rg = default_rng(seed=seed)

    # Resource capacity levels
    num_greeters = arg_dict['num_greeters']
    num_reg_staff = arg_dict['num_reg_staff']
    num_bd_tech = arg_dict['num_bd_tech']
    num_schedulers = arg_dict['num_schedulers']

    # Initialize the patient flow related attributes
    patient_arrival_rate = arg_dict['patient_arrival_rate']
    mean_interarrival_time = 1.0 / (patient_arrival_rate / 60.0)

    pct_want_appt = arg_dict['pct_want_appt']
    iron_check_time_mean = arg_dict['iron_check_time_mean']
    iron_check_time_sd = arg_dict['iron_check_time_sd']
    reg_time_mean = arg_dict['reg_time_mean']
    blooddraw_time_mean = arg_dict['blooddraw_time_mean']
    blooddraw_time_sd = arg_dict['blooddraw_time_sd']
    sched_time_mean = arg_dict['sched_time_mean']
    sched_time_sd = arg_dict['sched_time_sd']
    obs_time = arg_dict['obs_time']
    post_obs_time_mean = arg_dict['post_obs_time_mean']

    # Other parameters
    stoptime = arg_dict['stoptime']  # No more arrivals after this time
    quiet = arg_dict['quiet']
    scenario = arg_dict['scenario']

    # Run the simulation
    env = simpy.Environment()

    # Create a clinic to simulate
    clinic = BloodDonationClinic(env, num_greeters, num_reg_staff, num_bd_tech, num_schedulers,
                           mean_interarrival_time, pct_want_appt,
                           iron_check_time_mean, iron_check_time_sd,
                           reg_time_mean,
                           blooddraw_time_mean, blooddraw_time_sd,
                           sched_time_mean, sched_time_sd,
                           obs_time, post_obs_time_mean, rg
                           )

    # Initialize and register the run_clinic generator function
    env.process(
        run_clinic(env, clinic, stoptime=stoptime, quiet=quiet))

    # Launch the simulation
    env.run()

    # Create output files and basic summary stats
    if len(arg_dict['output_path']) > 0:
        output_dir = Path.cwd() / arg_dict['output_path']
    else:
        output_dir = Path.cwd()

    # Create paths for the output logs
    clinic_patient_log_path = output_dir / f'clinic_patient_log_{scenario}_{rep_num}.csv'
    bd_occupancy_df_path = output_dir / f'bd_occupancy_{scenario}_{rep_num}.csv'
    postbd_occupancy_df_path = output_dir / f'postbd_occupancy_{scenario}_{rep_num}.csv'

    # Create patient log dataframe and add scenario and rep number cols
    clinic_patient_log_df = pd.DataFrame(clinic.timestamps_list)
    clinic_patient_log_df['scenario'] = scenario
    clinic_patient_log_df['rep_num'] = rep_num

    # Reorder cols to get scenario and rep_num first
    num_cols = len(clinic_patient_log_df.columns)
    new_col_order = [-2, -1]
    new_col_order.extend([_ for _ in range(0, num_cols-2)])
    clinic_patient_log_df = clinic_patient_log_df.iloc[:, new_col_order]

    # Compute durations of interest for patient log
    clinic_patient_log_df = compute_durations(clinic_patient_log_df)

    # Create occupancy log dataframes and add scenario and rep number cols
    bd_occupancy_df = pd.DataFrame(clinic.bd_occupancy_list, columns=['ts', 'occ'])
    bd_occupancy_df['scenario'] = scenario
    bd_occupancy_df['rep_num'] = scenario
    num_cols = len(bd_occupancy_df.columns)
    new_col_order = [-2, -1]
    new_col_order.extend([_ for _ in range(0, num_cols - 2)])
    bd_occupancy_df = bd_occupancy_df.iloc[:, new_col_order]

    postbd_occupancy_df = pd.DataFrame(clinic.postbd_occupancy_list, columns=['ts', 'occ'])
    postbd_occupancy_df['scenario'] = scenario
    postbd_occupancy_df['rep_num'] = scenario
    num_cols = len(postbd_occupancy_df.columns)
    new_col_order = [-2, -1]
    new_col_order.extend([_ for _ in range(0, num_cols - 2)])
    postbd_occupancy_df = bd_occupancy_df.iloc[:, new_col_order]

    # Export logs to csv
    clinic_patient_log_df.to_csv(clinic_patient_log_path, index=False)
    #bd_occupancy_df.to_csv(bd_occupancy_df_path, index=False)
    #postbd_occupancy_df.to_csv(postbd_occupancy_df_path, index=False)

    # Note simulation end time
    end_time = env.now
    print(f"Simulation replication {rep_num} ended at time {end_time}")


def process_sim_output(csvs_path, scenario):
    """

    Parameters
    ----------
    csvs_path : Path object for location of simulation output patient log csv files
    scenario : str

    Returns
    -------
    Dict of dicts

    Keys are:

    'patient_log_rep_stats' --> Contains dataframes from describe on group by rep num. Keys are perf measures.
    'patient_log_ci' -->        Contains dictionaries with overall stats and CIs. Keys are perf measures.
    """

    dest_path = csvs_path / f"consolidated_clinic_patient_log_{scenario}.csv"

    sort_keys = ['scenario', 'rep_num']

    # Create empty dict to hold the DataFrames created as we read each csv file
    dfs = {}

    # Loop over all the csv files
    for csv_f in csvs_path.glob('clinic_patient_log_*.csv'):
        # Split the filename off from csv extension. We'll use the filename
        # (without the extension) as the key in the dfs dict.
        fstem = csv_f.stem

        # Read the next csv file into a pandas DataFrame and add it to
        # the dfs dict.
        df = pd.read_csv(csv_f)
        dfs[fstem] = df

    # Use pandas concat method to combine the file specific DataFrames into
    # one big DataFrame.
    patient_log_df = pd.concat(dfs)

    # Since we didn't try to control the order in which the files were read,
    # we'll sort the final DataFrame in place by the specified sort keys.
    patient_log_df.sort_values(sort_keys, inplace=True)

    # Export the final DataFrame to a csv file. Suppress the pandas index.
    patient_log_df.to_csv(dest_path, index=False)

    # Compute summary statistics for several performance measures
    patient_log_stats = summarize_patient_log(patient_log_df, scenario)

    # Now delete the individual replication files
    for csv_f in csvs_path.glob('clinic_patient_log_*.csv'):
        csv_f.unlink()

    return patient_log_stats


def summarize_patient_log(patient_log_df, scenario):
    """

    Parameters
    ----------
    patient_log_df : DataFrame created by process_sim_output
    scenario : str

    Returns
    -------
    Dict of dictionaries - See comments below
    """

    # Create empty dictionaries to hold computed results
    patient_log_rep_stats = {}  # Will store dataframes from describe on group by rep num. Keys are perf measures.
    patient_log_ci = {}         # Will store dictionaries with overall stats and CIs. Keys are perf measures.
    patient_log_stats = {}      # Container dict returned by this function containing the two previous dicts.

    # Create list of performance measures for looping over
    performance_measures = ['wait_for_greeter', 'wait_for_reg', 'wait_for_bd_tech',
                           'wait_for_scheduler', 'time_in_system']

    for pm in performance_measures:
        # Compute descriptive stats for each replication and store dataframe in dict
        patient_log_rep_stats[pm] = patient_log_df.groupby(['rep_num'])[pm].describe()
        # Compute across replication stats
        n_samples = patient_log_rep_stats[pm]['mean'].count()
        mean_mean = patient_log_rep_stats[pm]['mean'].mean()
        sd_mean = patient_log_rep_stats[pm]['mean'].std()
        ci_95_lower = mean_mean - 1.96 * sd_mean / math.sqrt(n_samples)
        ci_95_upper = mean_mean + 1.96 * sd_mean / math.sqrt(n_samples)
        # Store cross replication stats as dict in dict
        patient_log_ci[pm] = {'n_samples': n_samples, 'mean_mean': mean_mean, 'sd_mean': sd_mean,
                              'ci_95_lower': ci_95_lower, 'ci_95_upper': ci_95_upper}

    patient_log_stats['scenario'] = scenario
    patient_log_stats['patient_log_rep_stats'] = patient_log_rep_stats
    # Convert the final summary stats dict to a DataFrame
    patient_log_stats['patient_log_ci'] = pd.DataFrame(patient_log_ci)

    return patient_log_stats


def process_command_line():
    """
    Parse command line arguments

    `argv` is a list of arguments, or `None` for ``sys.argv[1:]``.
    Return a Namespace representing the argument list.
    """
    # Create the parser
    parser = argparse.ArgumentParser(prog='blood_donation_clinic_model',
                                     description='Run Blood Donation clinic simulation')

    # Add arguments
    parser.add_argument(
        "--config", type=str, default=None,
        help="Configuration file containing input parameter arguments and values"
    )

    parser.add_argument("--patient_arrival_rate", default=50, help="patients per hour",
                        type=float)

    parser.add_argument("--num_greeters", default=2, help="number of greeters",
                        type=int)

    parser.add_argument("--num_reg_staff", default=2, help="number of registration staff",
                        type=int)

    parser.add_argument("--num_bd_tech", default=10, help="number of blood draw technicians",
                        type=int)

    parser.add_argument("--num_schedulers", default=2, help="number of schedulers",
                        type=int)

    parser.add_argument("--pct_want_appt", default=0.5,
                        help="percent of patients wanting next donation scheduled(default = 0.5)",
                        type=float)

    parser.add_argument("--iron_check_time_mean", default=2.0,
                        help="Mean time (mins) for iron level check (default = 0.25)",
                        type=float)

    parser.add_argument("--iron_check_time_sd", default=0.5,
                        help="Standard deviation time (mins) for iron level check (default = 0.05)",
                        type=float)

    parser.add_argument("--reg_time_mean", default=1.0,
                        help="Mean time (mins) for registration (default = 1.0)",
                        type=float)

    parser.add_argument("--blooddraw_time_mean", default=20.0,
                        help="Mean time (mins) for blood draw donation (default = 4.0)",
                        type=float)

    parser.add_argument("--blooddraw_time_sd", default=5.0,
                        help="Standard deviation time (mins) for blood draw donation (default = 0.5)",
                        type=float)

    parser.add_argument("--sched_time_mean", default=1.0,
                        help="Mean time (mins) for scheduling next blood donation appt (default = 1.0)",
                        type=float)

    parser.add_argument("--sched_time_sd", default=1.0,
                        help="Standard deviation time (mins) for scheduling next blood donation appt (default = 0.1)",
                        type=float)

    parser.add_argument("--obs_time", default=15.0,
                        help="Time (minutes) patient waits post-blood draw in observation area (default = 15)",
                        type=float)

    parser.add_argument("--post_obs_time_mean", default=1.0,
                        help="Time (minutes) patient waits post OBS_TIME in observation area (default = 1.0)",
                        type=float)

    parser.add_argument(
        "--scenario", type=str, default=datetime.now().strftime("%Y.%m.%d.%H.%M."),
        help="Appended to output filenames."
    )

    parser.add_argument("--stoptime", default=600, help="time that simulation stops (default = 600)",
                        type=float)

    parser.add_argument("--num_reps", default=1, help="number of simulation replications (default = 1)",
                        type=int)

    parser.add_argument("--seed", default=3, help="random number generator seed (default = 3)",
                        type=int)

    parser.add_argument(
        "--output_path", type=str, default="", help="location for output file writing")

    parser.add_argument("--quiet", action='store_true',
                        help="If True, suppresses output messages (default=False")

    # do the parsing
    args = parser.parse_args()

    if args.config is not None:
        # Read inputs from config file
        with open(args.config, "r") as fin:
            args = parser.parse_args(fin.read().split())

    return args


def main():

    args = process_command_line()
    print(args)

    num_reps = args.num_reps
    scenario = args.scenario

    if len(args.output_path) > 0:
        output_dir = Path.cwd() / args.output_path
    else:
        output_dir = Path.cwd()

    # Main simulation replication loop
    for i in range(1, num_reps + 1):
        simulate(vars(args), i)

    # Consolidate the patient logs and compute summary stats
    patient_log_stats = process_sim_output(output_dir, scenario)
    print(f"\nScenario: {scenario}")
    pd.set_option("display.precision", 3)
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 120)
    print(patient_log_stats['patient_log_rep_stats'])
    print(patient_log_stats['patient_log_ci'])


if __name__ == '__main__':
    main()


