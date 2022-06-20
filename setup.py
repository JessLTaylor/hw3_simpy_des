from setuptools import find_packages, setup

setup(
    name='blood_donation_clinic',
    packages=find_packages("blood_donation_clinic"),
    package_dir={"": "blood_donation_clinic"},
    version='0.1.0',
    description='SimPy model of blood donation clinic',
    author='jtaylor',
    license='MIT',
)
