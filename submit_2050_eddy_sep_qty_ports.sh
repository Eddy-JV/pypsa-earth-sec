#!/bin/bash
#SBATCH --nodes=1
#SBATCH --partition=batch,cpu
#SBATCH --ntasks-per-node=32
#SBATCH --error='job-%j-error.out'
#SBATCH --output='job-%j-out.out'
#SBATCH --export=NONE
#SBATCH --chdir=/nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec
#SBATCH --mail-type=BEGIN,END,FAIL
#SBATCH --mail-user=eddy.jalbout@ieg.fraunhofer.de
echo $HOSTNAME

module purge
module load Anaconda3
module load Java
source activate /nfs/home/edd32710/.conda/envs/PES_Model

export GRB_LICENSE_FILE=/nfs/home/edd32710/gurobi.lic
export PYTHONNOUSERSITE=True

which python3
python3 -c "import sys;print(sys.path)"

cp /nimble/home/edd32710/.cdsapirc ~/.cdsapirc

# cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/resources/custom_data/pipelines_2050.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/resources/custom_data/pipelines.csv

# -----------------------------------------------
# 1 - Synthesis & Electrolysis = at_port
# -----------------------------------------------
rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec.nc
rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec_s.nc
    # -----------
    # Q0 - Cons
    # -----------
python modify_config_files_nh3_at_port.py
python modify_config_files_h2_at_port.py
# python modify_config_files_Q0_2050.py
# cp config.pypsa-earth_conservative_2050.yaml config.pypsa-earth.yaml
# cp config_2050_cons.yaml config.yaml
# snakemake -j 32 solve_all_networks
#     # -----------
#     # Q1 - Cons
#     # -----------
# python modify_config_files_Q1.py
# cp config_2050_cons.yaml config.yaml
# cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q1.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
# snakemake -j 32 solve_all_networks
#     # -----------
#     # Q2_rest - Cons
#     # -----------
# python modify_config_files_Q2_rest.py
# cp config_2050_cons.yaml config.yaml
# cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q_rest.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
# snakemake -j 32 solve_all_networks
    # ---------------------------------------------------------
# rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec.nc
# rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec_s.nc
#     -----------
#     Q0 - Real
#     -----------
python modify_config_files_Q0_2050.py
cp config.pypsa-earth_realistic_2050.yaml config.pypsa-earth.yaml
cp config_2050_real.yaml config.yaml
snakemake -j 32 solve_all_networks
    # -----------
    # Q1 - Real
    # -----------
# python modify_config_files_Q1.py
# cp config_2050_real.yaml config.yaml
# cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q1.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
# snakemake -j 32 solve_all_networks
    # -----------
    # Q2_rest - Real
    # -----------
python modify_config_files_Q2_rest.py
cp config_2050_real.yaml config.yaml
# cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q_rest.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
snakemake -j 32 solve_all_networks
    # ---------------------------------------------------------
# rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec.nc
# rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec_s.nc
#     # -----------
#     # Q0 - Opt
#     # -----------
python modify_config_files_Q0_2050.py
cp config.pypsa-earth_optimistic_2050.yaml config.pypsa-earth.yaml
cp config_2050_opt.yaml config.yaml
snakemake -j 32 solve_all_networks
# #     # -----------
# #     # Q1 - Opt
# #     # -----------
# # python modify_config_files_Q1.py
# # cp config_2050_opt.yaml config.yaml
# # cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q1.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
# # snakemake -j 32 solve_all_networks
# #     # -----------
# #     # Q2_rest - Opt
# #     # -----------
python modify_config_files_Q2_rest.py
cp config_2050_opt.yaml config.yaml
# # cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q_rest.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
snakemake -j 32 solve_all_networks



# -----------------------------------------------
# 2 - Electrolysis & Synthesis = free
# -----------------------------------------------
rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec.nc
rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec_s.nc
    # -----------
    # Q0 - Cons
    # -----------
python modify_config_files_nh3_free.py
python modify_config_files_h2_free.py
# python modify_config_files_Q0_2050.py
# cp config.pypsa-earth_conservative_2050.yaml config.pypsa-earth.yaml
# cp config_2050_cons.yaml config.yaml
# snakemake -j 32 solve_all_networks
#     # -----------
#     # Q1 - Cons
#     # -----------
# python modify_config_files_Q1.py
# cp config_2050_cons.yaml config.yaml
# cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q1.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
# snakemake -j 32 solve_all_networks
#     # -----------
#     # Q2_rest - Cons
#     # -----------
# python modify_config_files_Q2_rest.py
# cp config_2050_cons.yaml config.yaml
# cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q_rest.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
# snakemake -j 32 solve_all_networks
#     # ---------------------------------------------------------
# rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec.nc
# rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec_s.nc
    # -----------
    # Q0 - Real
    # -----------
python modify_config_files_Q0_2050.py
cp config.pypsa-earth_realistic_2050.yaml config.pypsa-earth.yaml
cp config_2050_real.yaml config.yaml
snakemake -j 32 solve_all_networks
    # -----------
    # Q1 - Real
    # -----------
# python modify_config_files_Q1.py
# cp config_2050_real.yaml config.yaml
# cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q1.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
# snakemake -j 32 solve_all_networks
    # -----------
    # Q2_rest - Real
    # -----------
python modify_config_files_Q2_rest.py
cp config_2050_real.yaml config.yaml
# cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q_rest.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
snakemake -j 32 solve_all_networks
    # ---------------------------------------------------------
rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec.nc
rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec_s.nc
    # -----------
    # Q0 - Opt
    # -----------
python modify_config_files_Q0_2050.py
cp config.pypsa-earth_optimistic_2050.yaml config.pypsa-earth.yaml
cp config_2050_opt.yaml config.yaml
snakemake -j 32 solve_all_networks
#     # -----------
#     # Q1 - Opt
#     # -----------
# python modify_config_files_Q1.py
# cp config_2050_opt.yaml config.yaml
# cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q1.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
# snakemake -j 32 solve_all_networks
#     # -----------
#     # Q2_rest - Opt
#     # -----------
python modify_config_files_Q2_rest.py
cp config_2050_opt.yaml config.yaml
# cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q_rest.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
snakemake -j 32 solve_all_networks








# # -----------------------------------------------
# # 3 - Electrolysis = free & Synthesis = at Port
# # -----------------------------------------------
# rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec.nc
# rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec_s.nc
# #     # -----------
# #     # Q0 - Cons
# #     # -----------
# python modify_config_files_nh3_at_port.py
# python modify_config_files_h2_free.py
# # python modify_config_files_Q0_2050.py
# # cp config.pypsa-earth_conservative_2050.yaml config.pypsa-earth.yaml
# # cp config_2050_cons.yaml config.yaml
# # snakemake -j 32 solve_all_networks
# #     # -----------
# #     # Q1 - Cons
# #     # -----------
# # python modify_config_files_Q1.py
# # cp config_2050_cons.yaml config.yaml
# # cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q1.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
# # snakemake -j 32 solve_all_networks
# #     # -----------
# #     # Q2_rest - Cons
# #     # -----------
# # python modify_config_files_Q2_rest.py
# # cp config_2050_cons.yaml config.yaml
# # cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q_rest.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
# # snakemake -j 32 solve_all_networks
# #     # ---------------------------------------------------------
# # rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec.nc
# # rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec_s.nc
#     # -----------
#     # Q0 - Real
#     # -----------
# python modify_config_files_Q0_2050.py
# cp config.pypsa-earth_realistic_2050.yaml config.pypsa-earth.yaml
# cp config_2050_real.yaml config.yaml
# snakemake -j 32 solve_all_networks
# #     # -----------
# #     # Q1 - Real
# #     # -----------
# # python modify_config_files_Q1.py
# # cp config_2050_real.yaml config.yaml
# # cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q1.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
# # snakemake -j 32 solve_all_networks
#     # -----------
#     # Q2_rest - Real
#     # -----------
# python modify_config_files_Q2_rest.py
# cp config_2050_real.yaml config.yaml
# # cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q_rest.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
# snakemake -j 32 solve_all_networks
# #     # ---------------------------------------------------------
# # rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec.nc
# # rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec_s.nc
# #     # -----------
# #     # Q0 - Opt
# #     # -----------
# # python modify_config_files_Q0_2050.py
# # cp config.pypsa-earth_optimistic_2050.yaml config.pypsa-earth.yaml
# # cp config_2050_opt.yaml config.yaml
# # snakemake -j 32 solve_all_networks
# #     -----------
# #     Q1 - Opt
# #     -----------
# # python modify_config_files_Q1.py
# # cp config_2050_opt.yaml config.yaml
# # cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q1.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
# # snakemake -j 32 solve_all_networks
# #     # -----------
# #     # Q2_rest - Opt
# #     # -----------
# # python modify_config_files_Q2_rest.py
# # cp config_2050_opt.yaml config.yaml
# # cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q_rest.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
# # snakemake -j 32 solve_all_networks





# # -----------------------------------------------
# # 4 - Electrolysis = at Port & Synthesis = free
# # -----------------------------------------------
# rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec.nc
# rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec_s.nc
# #     # -----------
# #     # Q0 - Cons
# #     # -----------
# python modify_config_files_nh3_free.py
# python modify_config_files_h2_at_port.py
# # python modify_config_files_Q0_2050.py
# # cp config.pypsa-earth_conservative_2050.yaml config.pypsa-earth.yaml
# # cp config_2050_cons.yaml config.yaml
# # snakemake -j 32 solve_all_networks
# #     # -----------
# #     # Q1 - Cons
# #     # -----------
# # python modify_config_files_Q1.py
# # cp config_2050_cons.yaml config.yaml
# # cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q1.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
# # snakemake -j 32 solve_all_networks
# #     # -----------
# #     # Q2_rest - Cons
# #     # -----------
# # python modify_config_files_Q2_rest.py
# # cp config_2050_cons.yaml config.yaml
# # cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q_rest.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
# # snakemake -j 32 solve_all_networks
# #     # ---------------------------------------------------------
# # rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec.nc
# # rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec_s.nc
#     # -----------
#     # Q0 - Real
#     # -----------
# python modify_config_files_Q0_2050.py
# cp config.pypsa-earth_realistic_2050.yaml config.pypsa-earth.yaml
# cp config_2050_real.yaml config.yaml
# snakemake -j 32 solve_all_networks
# #     # -----------
# #     # Q1 - Real
# #     # -----------
# # python modify_config_files_Q1.py
# # cp config_2050_real.yaml config.yaml
# # cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q1.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
# # snakemake -j 32 solve_all_networks
#     # -----------
#     # Q2_rest - Real
#     # -----------
# python modify_config_files_Q2_rest.py
# cp config_2050_real.yaml config.yaml
# # cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q_rest.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
# snakemake -j 32 solve_all_networks
# #     # ---------------------------------------------------------
# # rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec.nc
# # rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec_s.nc
# #     # -----------
# #     # Q0 - Opt
# #     # -----------
# # python modify_config_files_Q0_2050.py
# # cp config.pypsa-earth_optimistic_2050.yaml config.pypsa-earth.yaml
# # cp config_2050_opt.yaml config.yaml
# # snakemake -j 32 solve_all_networks
# #     -----------
# #     Q1 - Opt
# #     -----------
# # python modify_config_files_Q1.py
# # cp config_2050_opt.yaml config.yaml
# # cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q1.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
# # snakemake -j 32 solve_all_networks
# #     # -----------
# #     # Q2_rest - Opt
# #     # -----------
# # python modify_config_files_Q2_rest.py
# # cp config_2050_opt.yaml config.yaml
# # cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q_rest.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
# # snakemake -j 32 solve_all_networks


























# # -----------------------------------------------
# # h2_delivery = weekly
# # -----------------------------------------------
# rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec.nc
# rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec_s.nc
#     # -----------
#     # Q0 - Cons
#     # -----------
# python modify_config_files_weekly.py
# python modify_config_files_Q0_2050.py
# cp config.pypsa-earth_conservative_2050.yaml config.pypsa-earth.yaml
# cp config_2050_cons.yaml config.yaml
# snakemake -j 32 solve_all_networks
#     # -----------
#     # Q1 - Cons
#     # -----------
# python modify_config_files_Q1.py
# cp config_2050_cons.yaml config.yaml
# cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q1.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
# snakemake -j 32 solve_all_networks
#     # -----------
#     # Q2_rest - Cons
#     # -----------
# python modify_config_files_Q2_rest.py
# cp config_2050_cons.yaml config.yaml
# cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q_rest.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
# snakemake -j 32 solve_all_networks
#     # ---------------------------------------------------------
# rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec.nc
# rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec_s.nc
#     # -----------
#     # Q0 - Real
#     # -----------
# python modify_config_files_Q0_2050.py
# cp config.pypsa-earth_realistic_2050.yaml config.pypsa-earth.yaml
# cp config_2050_real.yaml config.yaml
# snakemake -j 32 solve_all_networks
#     # -----------
#     # Q1 - Real
#     # -----------
# python modify_config_files_Q1.py
# cp config_2050_real.yaml config.yaml
# cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q1.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
# snakemake -j 32 solve_all_networks
#     # -----------
#     # Q2_rest - Real
#     # -----------
# python modify_config_files_Q2_rest.py
# cp config_2050_real.yaml config.yaml
# cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q_rest.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
# snakemake -j 32 solve_all_networks
#     # ---------------------------------------------------------
# rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec.nc
# rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec_s.nc
#     # -----------
#     # Q0 - Opt
#     # -----------
# python modify_config_files_Q0_2050.py
# cp config.pypsa-earth_optimistic_2050.yaml config.pypsa-earth.yaml
# cp config_2050_opt.yaml config.yaml
# snakemake -j 32 solve_all_networks
#     # -----------
#     # Q1 - Opt
#     # -----------
# python modify_config_files_Q1.py
# cp config_2050_opt.yaml config.yaml
# cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q1.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
# snakemake -j 32 solve_all_networks
#     # -----------
#     # Q2_rest - Opt
#     # -----------
# python modify_config_files_Q2_rest.py
# cp config_2050_opt.yaml config.yaml
# cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q_rest.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
# snakemake -j 32 solve_all_networks




# # -----------------------------------------------
# # h2_delivery = daily
# # -----------------------------------------------
# rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec.nc
# rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec_s.nc
#     # -----------
#     # Q0 - Cons
#     # -----------
# python modify_config_files_daily.py
# python modify_config_files_Q0_2050.py
# cp config.pypsa-earth_conservative_2050.yaml config.pypsa-earth.yaml
# cp config_2050_cons.yaml config.yaml
# snakemake -j 32 solve_all_networks
#     # -----------
#     # Q1 - Cons
#     # -----------
# python modify_config_files_Q1.py
# cp config_2050_cons.yaml config.yaml
# cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q1.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
# snakemake -j 32 solve_all_networks
#     # -----------
#     # Q2_rest - Cons
#     # -----------
# python modify_config_files_Q2_rest.py
# cp config_2050_cons.yaml config.yaml
# cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q_rest.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
# snakemake -j 32 solve_all_networks
#     # ---------------------------------------------------------
# rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec.nc
# rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec_s.nc
#     # -----------
#     # Q0 - Real
#     # -----------
# python modify_config_files_Q0_2050.py
# cp config.pypsa-earth_realistic_2050.yaml config.pypsa-earth.yaml
# cp config_2050_real.yaml config.yaml
# snakemake -j 32 solve_all_networks
#     # -----------
#     # Q1 - Real
#     # -----------
# python modify_config_files_Q1.py
# cp config_2050_real.yaml config.yaml
# cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q1.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
# snakemake -j 32 solve_all_networks
#     # -----------
#     # Q2_rest - Real
#     # -----------
# python modify_config_files_Q2_rest.py
# cp config_2050_real.yaml config.yaml
# cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q_rest.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
# snakemake -j 32 solve_all_networks
#     # ---------------------------------------------------------
# rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec.nc
# rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec_s.nc
#     # -----------
#     # Q0 - Opt
#     # -----------
# python modify_config_files_Q0_2050.py
# cp config.pypsa-earth_optimistic_2050.yaml config.pypsa-earth.yaml
# cp config_2050_opt.yaml config.yaml
# snakemake -j 32 solve_all_networks
#     # -----------
#     # Q1 - Opt
#     # -----------
# python modify_config_files_Q1.py
# cp config_2050_opt.yaml config.yaml
# cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q1.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
# snakemake -j 32 solve_all_networks
#     # -----------
#     # Q2_rest - Opt
#     # -----------
# python modify_config_files_Q2_rest.py
# cp config_2050_opt.yaml config.yaml
# cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q_rest.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
# snakemake -j 32 solve_all_networks


# # -----------------------------------------------
# # h2_delivery = hourly
# # -----------------------------------------------
# rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec.nc
# rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec_s.nc
#     # -----------
#     # Q0 - Cons
#     # -----------
# python modify_config_files_hourly.py
# python modify_config_files_Q0_2050.py
# cp config.pypsa-earth_conservative_2050.yaml config.pypsa-earth.yaml
# cp config_2050_cons.yaml config.yaml
# snakemake -j 32 solve_all_networks
#     # -----------
#     # Q1 - Cons
#     # -----------
# python modify_config_files_Q1.py
# cp config_2050_cons.yaml config.yaml
# cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q1.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
# snakemake -j 32 solve_all_networks
#     # -----------
#     # Q2_rest - Cons
#     # -----------
# python modify_config_files_Q2_rest.py
# cp config_2050_cons.yaml config.yaml
# cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q_rest.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
# snakemake -j 32 solve_all_networks
#     # ---------------------------------------------------------
# rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec.nc
# rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec_s.nc
#     # -----------
#     # Q0 - Real
#     # -----------
# python modify_config_files_Q0_2050.py
# cp config.pypsa-earth_realistic_2050.yaml config.pypsa-earth.yaml
# cp config_2050_real.yaml config.yaml
# snakemake -j 32 solve_all_networks
#     # -----------
#     # Q1 - Real
#     # -----------
# python modify_config_files_Q1.py
# cp config_2050_real.yaml config.yaml
# cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q1.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
# snakemake -j 32 solve_all_networks
#     # -----------
#     # Q2_rest - Real
#     # -----------
# python modify_config_files_Q2_rest.py
# cp config_2050_real.yaml config.yaml
# cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q_rest.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
# snakemake -j 32 solve_all_networks
#     # ---------------------------------------------------------
# rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec.nc
# rm /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/pypsa-earth/networks/elec_s.nc
#     # -----------
#     # Q0 - Opt
#     # -----------
# python modify_config_files_Q0_2050.py
# cp config.pypsa-earth_optimistic_2050.yaml config.pypsa-earth.yaml
# cp config_2050_opt.yaml config.yaml
# snakemake -j 32 solve_all_networks
#     # -----------
#     # Q1 - Opt
#     # -----------
# python modify_config_files_Q1.py
# cp config_2050_opt.yaml config.yaml
# cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q1.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
# snakemake -j 32 solve_all_networks
#     # -----------
#     # Q2_rest - Opt
#     # -----------
# python modify_config_files_Q2_rest.py
# cp config_2050_opt.yaml config.yaml
# cp /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports_Q_rest.csv /nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/export_ports.csv
# snakemake -j 32 solve_all_networks