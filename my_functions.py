import numpy as np
import pandas as pd
from scipy import optimize
from numpy.random import default_rng
import simpy


#class Model():
    """Base class for models"""
    
def patient_arrivals(env, interarrival_time=5.0):
    """Generate patients according to a fixed time arrival process"""

    # Create a counter to keep track of number of patients generated and to serve as unique patient id
    patient = 0

    # Infinite loop for generating patients
    while True:

        # Generate next interarrival time (this will be more complicated later)
        iat = interarrival_time
        
        # This process will now yield to a 'timeout' event. This process will resume after iat time units.
        yield env.timeout(iat)

        # Okay, we're back. :) New patient generated = update counter of patients
        patient += 1
        
        print(f"Patient {patient} created at time {env.now}")
        
def simplified_blood_donation(env, name, mean_prebd_time, mean_bd_time, mean_postbd_time, bd_tech):
    """Process function modeling how a patient flows through system."""

    print(f"{name} entering blood donation clinic at {env.now:.4f}")
    
    # Yield for the pre-blood donation time
    yield env.timeout(rg.exponential(mean_prebd_time))
    
    # Request blood draw technician to start blood draw
    with bd_tech.request() as request:
        print(f"{name} requested blood draw tech at {env.now:.4f}")
        yield request
        print(f"{name} got blood draw tech at {env.now:.4f}")
        yield env.timeout(rg.normal(mean_bd_time, 0.5))
                          
    # Yield for the post-blood donation time
    yield env.timeout(mean_postbd_time)
    
    # The process is over, we would exit the clinic
    print(f"{name} exiting blood donation clinic at {env.now:.4f}")
    
def patient_arrivals_random_2(env, mean_interarrival_time, mean_prebd_time, mean_bd_time,
                              mean_postbd_time, bd_tech, rg=default_rng(0)):
    """Generate patients according to a Poisson arrival process"""

    # Create a counter to keep track of number of patients generated and to serve as unique patient id
    patient = 0

    # Infinite loop for generating patients
    while True:

        # Generate next interarrival time
        iat = rg.exponential(mean_interarrival_time)
        
        # This process will now yield to a 'timeout' event. This process will resume after iat time units.
        yield env.timeout(iat)

        # Update counter of patients
        patient += 1

        print(f"Patient{patient} created at time {env.now}")
               
        # Create and register the simplifed blood donation process in two steps
        
        # Create a new patient delay process generator object.
        patient_visit = simplified_blood_donation(env, 'Patient{}'.format(patient), 
                                               mean_prebd_time, mean_bd_time, mean_postbd_time, bd_tech)
        
        # Register the process with the simulation environment
        env.process(patient_visit)
        
        # Here's the one step version
        # env.process(simplified_blood_donation(env, 'Patient{}'.format(patient), 
        #                                      mean_prebd_time, mean_bd_time, mean_postbd_time, bd_tech))