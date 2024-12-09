# -*- coding: utf-8 -*-
import logging
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import fiona
import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from pypsa.components import component_attrs, components
from pypsa.descriptors import Dict
from shapely.geometry import Point
from vresutils.costdata import annuity
from pypsa.linopf import ilopf, network_lopf
from pypsa.linopt import define_constraints, get_var, join_exprs, linexpr


from itertools import product

import powerplantmatching as pm
import pypsa
import xarray as xr
from powerplantmatching.export import map_country_bus

from helpers import (locate_bus, override_component_attrs, prepare_costs, 
                    calculate_annual_investment, calculate_annuity,
                    configure_logging, extract_technology, get_bus_unit,
                    read_efficiencies, three_2_two_digits_country, lossy_bidirectional_links)

from add_export_supply_chain import (
    get_efficiency, 
    read_efficiencies,
    select_ports,
    get_shipping_distance,
    parse_json_to_geodataframe,
    )

# from solve_network import (
#     add_battery_constraints,
#     # add_nh3_store_cap
# )

logger = logging.getLogger(__name__)

idx = pd.IndexSlice


def add_nice_carrier_names(n, config):
    carrier_i = n.carriers.index
    nice_names = (
        pd.Series(config["plotting"]["nice_names"])
        .reindex(carrier_i)
        .fillna(carrier_i.to_series().str.title())
    )
    n.carriers["nice_name"] = nice_names
    colors = pd.Series(config["plotting"]["tech_colors"]).reindex(carrier_i)
    if colors.isna().any():
        missing_i = list(colors.index[colors.isna()])
        logger.warning(
            f"tech_colors for carriers {missing_i} not defined " "in config."
        )
    n.carriers["color"] = colors


def calculate_annuity(n, r):
    """
    Calculate the annuity factor for an asset with lifetime n years and
    discount rate of r, e.g. annuity(20, 0.05) * 20 = 1.6.
    """
    if isinstance(r, pd.Series):
        return pd.Series(1 / n, index=r.index).where(
            r == 0, r / (1.0 - 1.0 / (1.0 + r) ** n)
        )
    elif r > 0:
        return r / (1.0 - 1.0 / (1.0 + r) ** n)
    else:
        return 1 / n

def _add_missing_carriers_from_costs(n, costs, carriers):
    missing_carriers = pd.Index(carriers).difference(n.carriers.index)
    if missing_carriers.empty:
        return

    emissions_cols = (
        costs.columns.to_series().loc[lambda s: s.str.endswith("_emissions")].values
    )
    suptechs = missing_carriers.str.split("-").str[0]
    if "csp" in suptechs:
        suptechs = suptechs.str.replace("csp", "csp-tower")
    emissions = costs.loc[suptechs, emissions_cols].fillna(0.0)
    emissions.index = missing_carriers
    n.import_components_from_dataframe(emissions, "Carrier")


def load_costs(tech_costs, config, elec_config, Nyears=1):
    """
    Set all asset costs and other parameters.
    """
    costs = pd.read_csv(tech_costs, index_col=["technology", "parameter"]).sort_index()

    # correct units to MW and EUR
    costs.loc[costs.unit.str.contains("/kW"), "value"] *= 1e3
    costs.unit = costs.unit.str.replace("/kW", "/MW")
    costs.loc[costs.unit.str.contains("USD"), "value"] *= config["USD2013_to_EUR2013"]

    costs = costs.value.unstack().fillna(config["fill_values"])

    costs["capital_cost"] = (
        (
            calculate_annuity(costs["lifetime"], costs["discount rate"])
            + costs["FOM"] / 100.0
        )
        * costs["investment"]
        * Nyears
    )

    costs.at["OCGT", "fuel"] = costs.at["gas", "fuel"]
    costs.at["CCGT", "fuel"] = costs.at["gas", "fuel"]

    costs["marginal_cost"] = costs["VOM"] + costs["fuel"] / costs["efficiency"]

    costs = costs.rename(columns={"CO2 intensity": "co2_emissions"})
    # rename because technology data & pypsa earth costs.csv use different names
    # TODO: rename the technologies in hosted tutorial data to match technology data
    costs = costs.rename(
        {
            "hydrogen storage": "hydrogen storage tank",
            "hydrogen storage tank": "hydrogen storage tank",
            "hydrogen storage tank type 1": "hydrogen storage tank",
            "hydrogen underground storage": "hydrogen storage underground",
        },
    )

    costs.at["OCGT", "co2_emissions"] = costs.at["gas", "co2_emissions"]
    costs.at["CCGT", "co2_emissions"] = costs.at["gas", "co2_emissions"]

    costs.at["solar", "capital_cost"] = (
        config["rooftop_share"] * costs.at["solar-rooftop", "capital_cost"]
        + (1 - config["rooftop_share"]) * costs.at["solar-utility", "capital_cost"]
    )

    def costs_for_storage(store, link1, link2=None, max_hours=1.0):
        capital_cost = link1["capital_cost"] + max_hours * store["capital_cost"]
        if link2 is not None:
            capital_cost += link2["capital_cost"]
        return pd.Series(
            dict(capital_cost=capital_cost, marginal_cost=0.0, co2_emissions=0.0)
        )

    max_hours = elec_config["max_hours"]
    costs.loc["battery"] = costs_for_storage(
        costs.loc["battery storage"],
        costs.loc["battery inverter"],
        max_hours=max_hours["battery"],
    )
    costs.loc["H2"] = costs_for_storage(
        costs.loc["hydrogen storage tank"],
        costs.loc["fuel cell"],
        costs.loc["electrolysis"],
        max_hours=max_hours["H2"],
    )

    for attr in ("marginal_cost", "capital_cost"):
        overwrites = config.get(attr)
        if overwrites is not None:
            overwrites = pd.Series(overwrites)
            costs.loc[overwrites.index, attr] = overwrites

    return costs


def create_import_profile(sopts, h2export, yaml_content):
    """This function creates the import profile based on the annual export demand and resamples it to temp resolution obtained from the wildcard"""

    export_h2 = h2export * 1e6  # convert TWh to MWh 

    if (yaml_content["export"]["export_profile"] == "esc_scenarios") and (yaml_content["export"]["esc_scenarios"]["default"]["import_profile"] == "constant"):
        import_profile = export_h2 / 8760
        # frequency = snakemake.config["scenario"]["sopts"].lower()
        # snapshots = pd.date_range(freq=frequency, **snakemake.params.snapshots)
        snapshots = pd.date_range(freq="h", **yaml_content["snapshots"])
        import_profile = pd.Series(import_profile, index=snapshots)

    elif (yaml_content["export"]["export_profile"] == "esc_scenarios") and (yaml_content["export"]["esc_scenarios"]["default"]["import_profile"] == "esc_profile"):
        # Import hydrogen import profile 
        #------------------------------------------TODO correct this similar to Trace
        import_profile = pd.read_csv(snakemake.input.ship_profile, index_col=0)
        import_profile.index = pd.to_datetime(import_profile.index)
        import_profile = pd.Series(
            import_profile["profile"], index=pd.to_datetime(import_profile.index)
        )

        if np.abs(import_profile.sum() - export_h2) > 1:  # Threshold of 1 MWh
            logger.error(
                f"Sum of ship profile ({import_profile.sum()/1e6} TWh) does not match export demand ({export_h2} TWh)"
            )
            raise ValueError(
                f"Sum of ship profile ({import_profile.sum()/1e6} TWh) does not match export demand ({export_h2} TWh)"
            )
        #--------------------------------------------

    # Resample to temporal resolution defined in wildcard "sopts" with pandas resample
    sopts = sopts[0].split("-")

    import_profile = import_profile.resample(sopts[0].casefold()).mean()

    # revise logger msg
    export_type = yaml_content["export"]["export_profile"]
    logger.info(
        f"The yearly import demand is {export_h2/1e6} TWh, profile generated based on {export_type} method and resampled to {sopts[0]}"
    )

    return import_profile





def add_shipping_lh2(n, exp_nodes, imp_nodes, exp_ports, import_profile, x_import, y_import):
    # Buses: shipping_lh2
    n.madd("Bus", imp_nodes, suffix=" H2 (g) (imp)", carrier="H2", location=imp_nodes, unit="MW", x=import_ports.x, y=import_ports.y, country=import_ports.country),
    n.madd("Bus", exp_nodes, suffix=" H2 (l)", carrier="H2", location=exp_nodes, unit="MW", x=exp_ports.x, y=exp_ports.y, country=exp_ports.country),
    n.madd("Bus", imp_nodes, suffix=" H2 (l) (imp)", carrier="H2", location=imp_nodes, unit="MW", x=import_ports.x, y=import_ports.y, country=import_ports.country),
    n.madd("Bus", exp_nodes, suffix=" berth (exp)", carrier="H2", location=exp_nodes, unit="t", x=exp_ports.x, y=exp_ports.y, country=exp_ports.country),
    n.madd("Bus", imp_nodes, suffix=" berth (imp)", carrier="H2", location=imp_nodes, unit="t", x=import_ports.x, y=import_ports.y, country=import_ports.country),
    # n.madd("Bus", exp_nodes, suffix=" H2 (g) storage (exp)", carrier="H2", location=exp_nodes, unit="MW", x=exp_ports.x, y=exp_ports.y, country=exp_ports.country)


    # by design decision all buses busn (n>1, e.g. bus2, bus3, ...) either:
    # case 1. contribute to the output to bus1, e.g. bus2 feeds into bus1
    # or
    # case 2. both are fed by bus0.

    # Links: shipping_lh2
    n.madd(
        "Link",
        exp_nodes + " H2 liquefaction",
        bus0=exp_nodes + " H2",
        bus1=exp_nodes + " H2 (l)",
        bus2=exp_nodes,
        carrier="H2",
        efficiency= get_efficiency(efficiencies, 'H2 liquefaction', 'H2 (g)', 'H2 (l)'),
        # Case 1.:
        # Efficiencies are provided for the conversion from bus2 to bus1
        # and are thus weighted by the primary efficiency of bus1
        # Efficiencies have to become negative to correctly account for the flow.
        efficiency2= (
            (-1)
            * get_efficiency(efficiencies, 'H2 liquefaction', 'H2 (g)', 'H2 (l)')
            / get_efficiency(efficiencies, 'H2 liquefaction', 'electricity', 'H2 (l)')
        ),
        capital_cost=costs.at["H2 liquefaction", "fixed"],
        p_nom_extendable=True,
        lifetime=costs.at["H2 liquefaction", "lifetime"],
        p_min_pu=0,
        p_max_pu=1,
        scale_costs_based_on="bus0"
    )


    n.madd(
        "Link",
        imp_nodes + " H2 evaporation (imp)",
        bus0=imp_nodes + " H2 (l) (imp)",
        bus1=imp_nodes + " H2 (g) (imp)",
        bus2=exp_nodes,
        carrier="H2",
        efficiency= get_efficiency(efficiencies, 'H2 evaporation', 'H2 (l)', 'H2 (g)'),
        efficiency2= (
            (-1)
            * get_efficiency(efficiencies, 'H2 evaporation', 'H2 (l)', 'H2 (g)')
            / get_efficiency(efficiencies, 'H2 evaporation', 'electricity', 'H2 (g)')
        ),
        capital_cost=costs.at["H2 evaporation", "fixed"],
        p_nom_extendable=True,
        lifetime=costs.at["H2 evaporation", "lifetime"],
        p_min_pu=0,
        p_max_pu=1,
    )

    n.madd(
        "Link",
        exp_nodes + " ship loading (exp)",
        bus0=exp_nodes + " H2 (l)",
        bus1=exp_nodes + " berth (exp)",
        carrier="H2",
        efficiency= get_efficiency(efficiencies, 'ship loading', 'H2 (l)', 'berth'),
        p_nom_extendable=True,
        p_min_pu=0,
        p_max_pu=1,
    )

    n.madd(
        "Link",
        imp_nodes + " ship unloading (imp)",
        bus0=imp_nodes + " berth (imp)",
        bus1=imp_nodes + " H2 (l) (imp)",
        carrier="H2",
        efficiency= get_efficiency(efficiencies, 'ship unloading', 'berth', 'H2 (l)'),
        p_nom_extendable=True,
        p_min_pu=0,
        p_max_pu=1,
    )

    # n.madd(
    #     "Link",
    #     exp_nodes + " H2 storage compressor (exp)",
    #     bus0=exp_nodes + " H2",
    #     bus1=exp_nodes + " H2 (g) storage (exp)",
    #     bus2=exp_nodes,
    #     carrier="H2",
    #     efficiency=get_efficiency(efficiencies, 'H2 storage compressor', 'H2 (g)', 'H2 (g) storage'),
    #     efficiency2= (
    #         (-1)
    #         * get_efficiency(efficiencies, 'H2 storage compressor', 'H2 (g)', 'H2 (g) storage')
    #         / get_efficiency(efficiencies, 'H2 storage compressor', 'electricity', 'H2 (g) storage')
    #     ),
    #     capital_cost=costs.at["H2 (g) fill compressor station", "fixed"], # Needs to be checked . This is only for pipelines compressors.
    #     p_nom_extendable=True,
    #     lifetime=costs.at["H2 (g) fill compressor station", "lifetime"],
    #     p_min_pu=0,
    #     p_max_pu=1,
    # )

    # n.madd(
    #     "Link",
    #     exp_nodes + " H2 storage unstoring (exp)",
    #     bus0=exp_nodes + " H2 (g) storage (exp)",
    #     bus1=exp_nodes + " H2",
    #     bus2=exp_nodes,
    #     carrier="H2",
    #     efficiency=get_efficiency(efficiencies, 'H2 storage unstoring', 'H2 (g) storage', 'H2 (g)'),
    #     p_nom_extendable=True,
    #     p_min_pu=0,
    #     p_max_pu=1,
    # )

    # # Stores: shipping_lh2

    # n.madd(
    #     "Store",
    #     exp_nodes + " H2 storage tank incl. compressor (exp)",
    #     bus=exp_nodes + " H2 (g) storage (exp)",
    #     e_nom_extendable=True,
    #     carrier="H2",
    #     e_initial=0,  # actually not required, since e_cyclic=True
    #     marginal_cost=0,
    #     capital_cost= costs.at[
    #         "hydrogen storage tank type 1 including compressor", "fixed"
    #     ],
    #     e_cyclic=True,
    #     lifetime=costs.at["hydrogen storage tank type 1 including compressor", "lifetime"],
    # )

    n.madd(
        "Store",
        exp_nodes + " H2 (l) storage tank",
        bus=exp_nodes + " H2 (l)",
        e_nom_extendable=True,
        carrier="H2",
        e_initial=0,  # actually not required, since e_cyclic=True
        marginal_cost=0,
        capital_cost= costs.at[
            "H2 (l) storage tank", "fixed"
        ],
        e_cyclic=True,
        lifetime=costs.at["H2 (l) storage tank", "lifetime"],
    )

    n.madd(
        "Store",
        imp_nodes + " H2 (l) storage tank (imp)",
        bus=imp_nodes + " H2 (l) (imp)",
        e_nom_extendable=True,
        carrier="H2",
        e_initial=0,  # actually not required, since e_cyclic=True
        marginal_cost=0,
        capital_cost= costs.at[
            "H2 (l) storage tank", "fixed"
        ],
        e_cyclic=True,
        lifetime=costs.at["H2 (l) storage tank", "lifetime"],
    )


    # add H2 load bus
    n.add(
        "Bus",
        "H2 export load bus",
        carrier="H2",
        x=x_import,
        y=y_import,
    )

    # add H2 load links
    n.madd(
        "Link",
        imp_nodes + " H2 export load links",
        bus0=imp_nodes + " H2 (g) (imp)",
        bus1="H2 export load bus",
        p_nom_extendable=True,
    )

    # Load: shipping_lh2
    n.add(
        "Load",
        "H2 export load",
        bus="H2 export load bus",
        carrier="H2",
        p_set=import_profile,
    )



def add_shipping_lnh3(n, nodes, nodes_df, exp_nodes, imp_nodes, exp_ports, import_profile, x_import, y_import, yaml_content, import_ports, efficiencies, costs):

    n.add("Carrier", "NH3", nice_name="Ammonia")
    n.add("Carrier", "NH3 store", nice_name="Ammonia storage")
    n.add("Carrier", "N2", nice_name="Nitrogen")

    # if yaml_content["export"]["esc_scenarios"]["synthesis"] == "at_port":
    #     nodes = exp_nodes
    #     nodes_df = exp_ports
    
    nodes = exp_nodes
    nodes_df = exp_ports

    # Buses: shipping_lnh3 (Liquid Ammonia)
    n.madd("Bus", nodes, suffix=" NH3 (g)", carrier="NH3", location=nodes, unit="MW", x=nodes_df.x, y=nodes_df.y, country=nodes_df.country.iloc[0]),
    n.madd("Bus", nodes, suffix=" NH3 (l)", carrier="NH3 store", location=nodes, unit="MW", x=nodes_df.x, y=nodes_df.y, country=nodes_df.country.iloc[0]),
    n.madd("Bus", imp_nodes, suffix=" NH3 (l) (imp)", carrier="NH3", location=imp_nodes, unit="MW", x=import_ports.x, y=import_ports.y, country=import_ports.country.iloc[0]),
    n.madd("Bus", imp_nodes, suffix=" NH3 (g) (imp)", carrier="NH3", location=imp_nodes, unit="MW", x=import_ports.x, y=import_ports.y, country=import_ports.country.iloc[0]),
    n.madd("Bus", nodes, suffix=" N2 (g)", carrier="N2", location=nodes, unit="MW", x=nodes_df.x, y=nodes_df.y, country=nodes_df.country.iloc[0]),
    n.madd("Bus", exp_nodes, suffix=" berth (exp)", carrier="NH3", location=exp_nodes, unit="t", x=exp_ports.x, y=exp_ports.y, country=exp_ports.country.iloc[0]),
    n.madd("Bus", imp_nodes, suffix=" berth (imp)", carrier="NH3", location=imp_nodes, unit="t", x=import_ports.x, y=import_ports.y, country=import_ports.country.iloc[0]),



    """ by design decision all buses busn (n>1, e.g. bus2, bus3, ...) either:
     case 1. contribute to the output to bus1, e.g. bus2 feeds into bus1
     or
     case 2. both are fed by bus0."""

    n.madd(
        "Link",
        nodes + " air separation unit",
        bus0=nodes,
        bus1=nodes + " N2 (g)",
        carrier="N2",
        efficiency= get_efficiency(efficiencies, 'NH3 liquefaction', 'NH3 (g)', 'NH3 (l)'),
        capital_cost=costs.at["air separation unit", "fixed"],
        p_nom_extendable=True,
        lifetime=costs.at["air separation unit", "lifetime"],
        p_min_pu=0,
        p_max_pu=1,
        scale_costs_based_on="bus1",
    )

    n.madd(
        "Link",
        nodes + " Haber-Bosch",
        bus0=nodes,
        bus1=nodes + " NH3 (g)",
        bus2=nodes + " N2 (g)",
        bus3=nodes + " H2",
        carrier="NH3 Haber-Bosch",
        efficiency= get_efficiency(efficiencies, 'Haber-Bosch', 'electricity', 'NH3 (g)'),
        efficiency2= (
            (-1)
            * get_efficiency(efficiencies, 'Haber-Bosch', 'electricity', 'NH3 (g)')
            / get_efficiency(efficiencies, 'Haber-Bosch', 'N2 (g)', 'NH3 (g)')
        ),
        efficiency3= (
            (-1)
            * get_efficiency(efficiencies, 'Haber-Bosch', 'electricity', 'NH3 (g)')
            / get_efficiency(efficiencies, 'Haber-Bosch', 'H2 (g)', 'NH3 (g)')
        ),
        capital_cost=costs.at["Haber-Bosch", "fixed"],
        p_nom_extendable=True,
        lifetime=costs.at["Haber-Bosch", "lifetime"],
        p_min_pu=0.3,
        p_max_pu=1,
        scale_costs_based_on="bus1",
    )



    n.madd(
        "Link",
        nodes + " NH3 liquefaction",
        bus0=nodes + " NH3 (g)",
        bus1=nodes + " NH3 (l)",
        bus2=nodes,
        carrier="NH3 liquefaction",
        efficiency= get_efficiency(efficiencies, 'NH3 liquefaction', 'NH3 (g)', 'NH3 (l)'),
        efficiency2= (
            (-1)
            * get_efficiency(efficiencies, 'NH3 liquefaction', 'NH3 (g)', 'NH3 (l)')
            / get_efficiency(efficiencies, 'NH3 liquefaction', 'electricity', 'NH3 (l)')
        ),
        # capital_cost=costs.at["H2 liquefaction", "fixed"], # lIQUEFACTION COSTS ARE INCLUDED IN THE NH3 STORAGE TANK COSTS
        p_nom_extendable=True,
        # lifetime=costs.at["H2 liquefaction", "lifetime"],
        p_min_pu=0,
        p_max_pu=1,
    )

    n.madd(
        "Link",
        imp_nodes + " NH3 evaporation (imp)",
        bus0=imp_nodes + " NH3 (l) (imp)",
        bus1=imp_nodes + " NH3 (g) (imp)",
        carrier="NH3 evaporation",
        efficiency= get_efficiency(efficiencies, 'NH3 evaporation', 'NH3 (l)', 'NH3 (g)'),
        # capital_cost=costs.at["H2 evaporation", "fixed"], # NO entries in costs.csv
        p_nom_extendable=True,
        # lifetime=costs.at["H2 evaporation", "lifetime"], # NO entries in costs.csv
        p_min_pu=0,
        p_max_pu=1,
    )

    if yaml_content["export"]["esc_scenarios"]["synthesis"]  == "free":

        attrs = ["bus0", "bus1", "length"]
        nh3_links = pd.DataFrame(columns=attrs)

        candidates = pd.concat(
            {
                "lines": n.lines[attrs],
                "links": n.links.loc[n.links.carrier == "DC", attrs],
            }
        )

        for candidate in candidates.index:
            buses = [
                candidates.at[candidate, "bus0"],
                candidates.at[candidate, "bus1"],
            ]
            buses.sort()
            name = f"NH3 pipeline {buses[0]} -> {buses[1]}"
            if name not in nh3_links.index:
                nh3_links.at[name, "bus0"] = buses[0]
                nh3_links.at[name, "bus1"] = buses[1]
                nh3_links.at[name, "length"] = candidates.at[candidate, "length"]


        # pipeline_sizes = {
        #     "size_0_15": {"upper_lim": 15, "lower_lim":0, "cost":9783},
        #     "size_16_30": {"upper_lim": 30, "lower_lim":16, "cost":6486},
        #     "size_31_100": {"upper_lim": 100, "lower_lim":31, "cost":2658},
        #     "size_101_300": {"upper_lim": 300, "lower_lim":101, "cost":1276},
        #     "size_301_500": {"upper_lim": 500, "lower_lim":301, "cost":744},
        #     "size_501_1000": {"upper_lim": 1000, "lower_lim":501, "cost":425},
        #     "size_1001_above": {"upper_lim": np.inf, "lower_lim":1001, "cost":212},
        #     }

        # for pipeline_size in pipeline_sizes:
        #     n.madd(
        #         "Link",
        #         nh3_links.index + " " + pipeline_size,
        #         bus0=nh3_links.bus0.values + " NH3 (l)",
        #         bus1=nh3_links.bus1.values + " NH3 (l)",
        #         p_min_pu=-1,
        #         # p_nom_min=snakemake.params.p_nom_min_pipeline,
        #         p_nom_max=pipeline_sizes[pipeline_size]["upper_lim"],
        #         p_nom=pipeline_sizes[pipeline_size]["lower_lim"],
        #         p_nom_extendable=True,
        #         length=nh3_links.length.values,
        #         capital_cost=pipeline_sizes[pipeline_size]["cost"] * nh3_links.length.values,
        #         carrier="NH3 pipeline",
        #         type=pipeline_size,
        #         lifetime=costs.at["NH3 (l) pipeline", "lifetime"],
        #         terrain_factor=snakemake.params.terrain_factor_pipeline,
        #         # efficiency=costs.at["NH3 (l) pipeline", "efficiency"],# ** (nh3_links.length.values / 1000)
        #     )

        n.madd(
            "Link",
            nh3_links.index,
            bus0=nh3_links.bus0.values + " NH3 (l)",
            bus1=nh3_links.bus1.values + " NH3 (l)",
            p_min_pu=-1,
            # p_nom_min=snakemake.params.p_nom_min_pipeline,
            p_nom_extendable=True,
            length=nh3_links.length.values,
            capital_cost=costs.at["NH3 (l) pipeline", "fixed"] * nh3_links.length.values,
            carrier="NH3 pipeline",
            lifetime=costs.at["NH3 (l) pipeline", "lifetime"],
            terrain_factor=yaml_content["costs"]["pipelines"]["length_factor"],
            # efficiency=costs.at["NH3 (l) pipeline", "efficiency"],# ** (nh3_links.length.values / 1000)
        )

    n.madd(
        "Link",
        exp_nodes + " ship loading (exp)",
        bus0=exp_nodes + " NH3 (l)",
        bus1=exp_nodes + " berth (exp)",
        carrier="NH3 ship loading",
        efficiency= get_efficiency(efficiencies, 'ship loading', 'NH3 (l)', 'berth'),
        p_nom_extendable=True,
        p_min_pu=0,
        p_max_pu=1,
    )

    n.madd(
        "Link",
        imp_nodes + " ship unloading (imp)",
        bus0=imp_nodes + " berth (imp)",
        bus1=imp_nodes + " NH3 (l) (imp)",
        carrier="NH3 ship unloading",
        efficiency= get_efficiency(efficiencies, 'ship unloading', 'berth', 'NH3 (l)'),
        p_nom_extendable=True,
        p_min_pu=0,
        p_max_pu=1,
    )

    

    # Stores: shipping_lnh3
    n.madd(
        "Store",
        nodes + " NH3 (l) storage tank incl. liquefaction",
        bus=nodes + " NH3 (l)",
        e_nom_extendable=True,
        carrier="NH3 store",
        e_initial=0,  # actually not required, since e_cyclic=True
        marginal_cost=0,
        capital_cost= costs.at[
            "NH3 (l) storage tank incl. liquefaction", "fixed"
        ],
        e_cyclic=True,
        lifetime=costs.at["NH3 (l) storage tank incl. liquefaction", "lifetime"],
    )



    n.madd(
        "Store",
        imp_nodes + " NH3 (l) storage tank incl. liquefaction (imp)",
        bus=imp_nodes + " NH3 (l) (imp)",
        e_nom_extendable=True,
        carrier="NH3 store imp",
        e_initial=0,  # actually not required, since e_cyclic=True
        marginal_cost=0,
        capital_cost= costs.at[
            "NH3 (l) storage tank incl. liquefaction", "fixed"
        ],
        e_cyclic=True,
        lifetime=costs.at["NH3 (l) storage tank incl. liquefaction", "lifetime"],
    )


    # add ammonia load bus
    n.add(
        "Bus",
        "NH3 export load bus",
        carrier="NH3",
        x=x_import,
        y=y_import,
    )

    # add ammonia load links
    n.madd(
        "Link",
        imp_nodes + " NH3 load links",
        bus0=imp_nodes + " NH3 (g) (imp)",
        bus1="NH3 export load bus",
        p_nom_extendable=True,
    )

    # Load: shipping_lnh3
    n.add(
        "Load",
        "NH3 export load",
        bus="NH3 export load bus",
        carrier="NH3",
        p_set=import_profile,
    )


def add_shipping_meoh(n, nodes, nodes_df, exp_nodes, imp_nodes, exp_ports, import_profile, x_import, y_import):

    n.add("Carrier", "meOH", nice_name="Methanol")
    n.add("Carrier", "DAC for meOH", nice_name="Direct Air Capture for Methanol")
    

    if yaml_content["export"]["esc_scenarios"]["synthesis"]  == "at_port":
        nodes = exp_nodes
        nodes_df = exp_ports

    # Buses: shipping_meoh (Methanol)
    # n.madd("Bus", exp_nodes, suffix=" battery (exp)", carrier="battery", location=exp_nodes, unit="MW", x=exp_ports.x, y=exp_ports.y, country=exp_ports.country.iloc[0]),
    n.madd("Bus", nodes, suffix=" meOH", carrier="meOH", location=nodes, unit="MW", x=nodes_df.x, y=nodes_df.y, country=nodes_df.country.iloc[0]),
    n.madd("Bus", imp_nodes, suffix=" meOH (imp)", carrier="meOH", location=imp_nodes, unit="MW", x=import_ports.x, y=import_ports.y, country=import_ports.country.iloc[0]),
    n.madd("Bus", nodes, suffix=" meOH storage", carrier="meOH", location=nodes, unit="m^3", x=nodes_df.x, y=nodes_df.y, country=nodes_df.country.iloc[0]),
    n.madd("Bus", nodes, suffix=" heat", carrier="heat", location=nodes, unit="MW", x=nodes_df.x, y=nodes_df.y, country=nodes_df.country.iloc[0]),
    n.madd("Bus", nodes, suffix=" CO2 (g)", carrier="co2", location=nodes, unit="t", x=nodes_df.x, y=nodes_df.y, country=nodes_df.country.iloc[0]),
    n.madd("Bus", nodes, suffix=" CO2 (l)", carrier="co2", location=nodes, unit="t", x=nodes_df.x, y=nodes_df.y, country=nodes_df.country.iloc[0]),
    n.madd("Bus", exp_nodes, suffix=" berth (exp)", carrier="meOH", location=exp_nodes, unit="t", x=exp_ports.x, y=exp_ports.y, country=exp_ports.country.iloc[0]),
    n.madd("Bus", imp_nodes, suffix=" berth (imp)", carrier="meOH", location=imp_nodes, unit="t", x=import_ports.x, y=import_ports.y, country=import_ports.country.iloc[0]),
    n.madd("Bus", imp_nodes, suffix=" meOH storage (imp)", carrier="meOH", location=imp_nodes, unit="m^3", x=import_ports.x, y=import_ports.y, country=import_ports.country.iloc[0]),
    # n.madd("Bus", exp_nodes, suffix=" H2 (g) storage (exp)", carrier="H2", location=exp_nodes, unit="MWh", x=exp_ports.x, y=exp_ports.y, country=exp_ports.country.iloc[0])


    """ by design decision all buses busn (n>1, e.g. bus2, bus3, ...) either:
     case 1. contribute to the output to bus1, e.g. bus2 feeds into bus1
     or
     case 2. both are fed by bus0."""

    # Links: shipping_meoh

    n.madd(
        "Link",
        nodes + " industrial heat pump medium temperature",
        bus0=nodes,
        bus1=nodes + " heat",
        carrier="heat",
        efficiency= get_efficiency(efficiencies, 'industrial heat pump medium temperature', 'electricity', 'heat'),
        capital_cost=costs.at["industrial heat pump medium temperature", "fixed"],
        p_nom_extendable=True,
        lifetime=costs.at["industrial heat pump medium temperature", "lifetime"],
        p_min_pu=0,
        p_max_pu=1,
        scale_costs_based_on="bus1",
    )

    # n.madd(
    #     "Link",
    #     nodes + " direct air capture",
    #     bus0=nodes,
    #     bus1=nodes + " CO2 (g)",
    #     bus2=nodes + " heat",
    #     carrier="co2",
    #     efficiency= get_efficiency(efficiencies, 'direct air capture', 'electricity', 'CO2 (g)'),
    #     efficiency2= (
    #         (-1)
    #         * get_efficiency(efficiencies, 'direct air capture', 'electricity', 'CO2 (g)')
    #         / get_efficiency(efficiencies, 'direct air capture', 'heat', 'CO2 (g)')
    #     ),
    #     capital_cost=costs.at["direct air capture", "fixed"],
    #     p_nom_extendable=True,
    #     lifetime=costs.at["direct air capture", "lifetime"],
    #     p_min_pu=0,
    #     p_max_pu=1,
    #     scale_costs_based_on="bus1",
    # )


    n.madd(
        "Link",
        nodes + " DAC for meOH",
        bus0="co2 atmosphere",
        bus1=nodes + " CO2 (g)",
        bus2=nodes,
        bus3=nodes + " heat",
        carrier="DAC for meOH",
        efficiency=1.0,
        efficiency2= -(
            costs.at["direct air capture", "electricity-input"]
            + costs.at["direct air capture", "compression-electricity-input"]
        ),
        efficiency3=  -(
            costs.at["direct air capture", "heat-input"]
            - costs.at["direct air capture", "compression-heat-output"]
        ),
        capital_cost=costs.at["direct air capture", "fixed"],
        p_nom_extendable=True,
        lifetime=costs.at["direct air capture", "lifetime"],
        p_min_pu=0,
        p_max_pu=1,
        scale_costs_based_on="bus1",
    )

    n.madd(
        "Link",
        nodes + " co2 feed from network",
        bus0=nodes + " co2 stored",
        bus1=nodes + " CO2 (g)",
        carrier="co2", # Do we need another naming for this?
        capital_cost=0,
        p_nom_extendable=True,
        p_min_pu=0,
        p_max_pu=1,
    )

    n.madd(
        "Link",
        nodes + " methanolisation",
        bus0=nodes,
        bus1=nodes + " meOH",
        bus2=nodes + " CO2 (g)",
        bus3=nodes + " H2",
        carrier="meOH",
        efficiency= get_efficiency(efficiencies, 'methanolisation', 'electricity', 'MeOH'),
        efficiency2= (
            (-1)
            * get_efficiency(efficiencies, 'methanolisation', 'electricity', 'MeOH')
            / get_efficiency(efficiencies, 'methanolisation', 'CO2 (g)', 'MeOH')
        ),
        efficiency3= (
            (-1)
            * get_efficiency(efficiencies, 'methanolisation', 'electricity', 'MeOH')
            / get_efficiency(efficiencies, 'methanolisation', 'H2 (g)', 'MeOH')
        ),
        capital_cost=costs.at["methanolisation", "fixed"],
        p_nom_extendable=True,
        lifetime=costs.at["methanolisation", "lifetime"],
        p_min_pu=0.9425,
        p_max_pu=1,
        scale_costs_based_on="bus1",
    )



    n.madd(
        "Link",
        nodes + " CO2 liquefaction",
        bus0=nodes,
        bus1=nodes + " CO2 (l)",
        bus2=nodes + " CO2 (g)",
        bus3=nodes + " heat",
        carrier="co2",
        efficiency= get_efficiency(efficiencies, 'CO2 liquefaction', 'electricity', 'CO2 (l)'),
        efficiency2= (
            (-1)
            * get_efficiency(efficiencies, 'CO2 liquefaction', 'electricity', 'CO2 (l)')
            / get_efficiency(efficiencies, 'CO2 liquefaction', 'CO2 (g)', 'CO2 (l)')
        ),
        efficiency3= (
            (-1)
            * get_efficiency(efficiencies, 'CO2 liquefaction', 'electricity', 'CO2 (l)')
            / get_efficiency(efficiencies, 'CO2 liquefaction', 'heat', 'CO2 (l)')
        ),
        capital_cost=costs.at["CO2 liquefaction", "fixed"],
        p_nom_extendable=True,
        lifetime=costs.at["CO2 liquefaction", "lifetime"],
        p_min_pu=0,
        p_max_pu=1,
        scale_costs_based_on="bus1",
    )

    n.madd(
        "Link",
        nodes + " CO2 evaporation",
        bus0=nodes + " CO2 (l)",
        bus1=nodes + " CO2 (g)",
        carrier="co2",
        efficiency= get_efficiency(efficiencies, 'CO2 evaporation', 'CO2 (l)', 'CO2 (g)'),
        # capital_cost=costs.at["H2 evaporation", "fixed"], # NO entries in costs.csv
        p_nom_extendable=True,
        # lifetime=costs.at["H2 evaporation", "lifetime"], # NO entries in costs.csv
        p_min_pu=0,
        p_max_pu=1,
    )


    if yaml_content["export"]["esc_scenarios"]["synthesis"]  == "free":

        attrs = ["bus0", "bus1", "length"]
        meOH_links = pd.DataFrame(columns=attrs)

        candidates = pd.concat(
            {
                "lines": n.lines[attrs],
                "links": n.links.loc[n.links.carrier == "DC", attrs],
            }
        )

        for candidate in candidates.index:
            buses = [
                candidates.at[candidate, "bus0"],
                candidates.at[candidate, "bus1"],
            ]
            buses.sort()
            name = f"meOH pipeline {buses[0]} -> {buses[1]}"
            if name not in meOH_links.index:
                meOH_links.at[name, "bus0"] = buses[0]
                meOH_links.at[name, "bus1"] = buses[1]
                meOH_links.at[name, "length"] = candidates.at[candidate, "length"]

        n.madd(
            "Link",
            meOH_links.index,
            bus0=meOH_links.bus0.values + " meOH",
            bus1=meOH_links.bus1.values + " meOH",
            p_min_pu=-1,
            # p_nom_min=snakemake.params.p_nom_min_pipeline,
            p_nom_extendable=True,
            length=meOH_links.length.values,
            capital_cost=costs.at["NH3 (l) pipeline", "fixed"] * meOH_links.length.values, # Same costs as NH3
            carrier="meOH pipeline",
            lifetime=costs.at["NH3 (l) pipeline", "lifetime"],
            terrain_factor=snakemake.params.terrain_factor_pipeline,
        )

    n.madd(
        "Link",
        exp_nodes + " ship loading (exp)",
        bus0=exp_nodes + " meOH",
        bus1=exp_nodes + " berth (exp)",
        carrier="meOH",
        efficiency= get_efficiency(efficiencies, 'ship loading', 'MeOH', 'berth'),
        p_nom_extendable=True,
        p_min_pu=0,
        p_max_pu=1,
    )

    n.madd(
        "Link",
        imp_nodes + " ship unloading (imp)",
        bus0=imp_nodes + " berth (imp)",
        bus1=imp_nodes + " meOH (imp)",
        carrier="meOH",
        efficiency= get_efficiency(efficiencies, 'ship unloading', 'berth', 'MeOH'),
        p_nom_extendable=True,
        p_min_pu=0,
        p_max_pu=1,
    )


    n.madd(
        "Link",
        nodes + " MeOH storing and unstoring",
        bus0=nodes + " meOH",
        bus1=nodes + " meOH storage",
        carrier="meOH",
        efficiency=get_efficiency(efficiencies, 'MeOH storing and unstoring', 'MeOH', 'MeOH storage'),
        p_nom_extendable=True,
        p_min_pu=-1,
        p_max_pu=1,
    )

    n.madd(
        "Link",
        imp_nodes + " MeOH storing and unstoring (imp)",
        bus0=imp_nodes + " meOH (imp)",
        bus1=imp_nodes + " meOH storage (imp)",
        carrier="meOH",
        efficiency=get_efficiency(efficiencies, 'MeOH storing and unstoring', 'MeOH', 'MeOH storage'),
        p_nom_extendable=True,
        p_min_pu=-1,
        p_max_pu=1,
    )

    # Stores: shipping_meoh

    n.madd(
        "Store",
        nodes + " CO2 storage tank",
        bus=nodes + " CO2 (l)",
        e_nom_extendable=True,
        carrier="co2",
        e_initial=0,  # actually not required, since e_cyclic=True
        marginal_cost=0,
        capital_cost= costs.at[
            "CO2 storage tank", "fixed"
        ],
        e_cyclic=True,
        lifetime=costs.at["CO2 storage tank", "lifetime"],
    )

    n.madd(
        "Store",
        nodes + " General liquid hydrocarbon storage (product)",
        bus=nodes + " meOH storage",
        e_nom_extendable=True,
        carrier="meOH",
        e_initial=0,  # actually not required, since e_cyclic=True
        marginal_cost=0,
        capital_cost= costs.at[
            "General liquid hydrocarbon storage (product)", "fixed"
        ],
        e_cyclic=True,
        lifetime=costs.at["General liquid hydrocarbon storage (product)", "lifetime"],
    )

    n.madd(
        "Store",
        imp_nodes + " General liquid hydrocarbon storage (product)",
        bus=imp_nodes + " meOH storage (imp)",
        e_nom_extendable=True,
        carrier="meOH",
        e_initial=0,  # actually not required, since e_cyclic=True
        marginal_cost=0,
        capital_cost= costs.at[
            "General liquid hydrocarbon storage (product)", "fixed"
        ],
        e_cyclic=True,
        lifetime=costs.at["General liquid hydrocarbon storage (product)", "lifetime"],
    )



    # add methanol load bus
    n.add(
        "Bus",
        "meOH export load bus",
        carrier="meOH",
        x=x_import,
        y=y_import,
    )

    # add methanol load links
    n.madd(
        "Link",
        imp_nodes + " meOH load links",
        bus0=imp_nodes + " meOH (imp)",
        bus1="meOH export load bus",
        p_nom_extendable=True,
    )

    # Load: shipping_meoh
    n.add(
        "Load",
        "meOH export load",
        bus="meOH export load bus",
        carrier="meOH",
        p_set=import_profile,
    )




def add_esc_shipping(n, dr, efficiencies_path, yaml_content, export_esc, costs_path):
    """Adds optional shipping routes to the network.

    Checks whether shipping for the wildcard "ESC" exists and - if it does - constructs
    a shipping route with multiple convoys (as optimisation options) for this route
    using standard PyPSA components.

    """

    from helpers import calculate_annuity
    
    props = pd.read_csv(
        "/nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/data/esc_data/shipping.csv",
        comment="#",
        index_col=["name", "variable"],
    )

    esc_ship_props={
        "shipping_lh2" : "H2 (l) transport ship",
        "shipping_lnh3" : "NH3 (l) transport ship",
        "shipping_meoh" : "MeOH transport ship",
    }

    # Get the buses for 'berth (imp)' and 'berth (exp)'
    berth_imp_buses = n.buses.filter(like='berth (imp)', axis=0)
    berth_exp_buses = n.buses.filter(like='berth (exp)', axis=0)

    # Get the index values for 'berth (imp)' and 'berth (exp)'
    berth_imp_index = n.buses.filter(like='berth (imp)', axis=0).index.tolist()
    berth_exp_index = n.buses.filter(like='berth (exp)', axis=0).index.tolist()

    # Create all combinations
    combinations = list(product(berth_exp_index, berth_imp_index))

    # Create DataFrame
    ships = pd.DataFrame(combinations, columns=['bus0', 'bus1'])

    # Add 'name' column if necessary
    ships['name'] = esc_ship_props[export_esc]

    # Set 'name' as index
    ships.set_index('name', inplace=True)

    # Add a column for the combinatino of exp-imp ports
    ships['combi'] = ships['bus0'].str.replace('berth \(exp\)', '', regex=True) +' --> '+ ships['bus1'].str.replace('berth \(imp\)', '', regex=True)

    # Merge the ships DataFrame with the berth_exp_buses DataFrame based on the 'bus0' column
    ships = pd.merge(ships, berth_exp_buses[['x', 'y', 'country']], left_on='bus0', right_index=True, how='left')

    # Rename the columns to 'x_bus1' and 'y_bus1'
    ships.rename(columns={'x': 'x_bus0', 'y': 'y_bus0', 'country': 'country_bus0'}, inplace=True)

    # Merge the ships DataFrame with the berth_imp_buses DataFrame based on the 'bus1' column
    ships = pd.merge(ships, berth_imp_buses[['x', 'y', 'country']], left_on='bus1', right_index=True, how='left')

    # Rename the columns to 'x_bus1' and 'y_bus1'
    ships.rename(columns={'x': 'x_bus1', 'y': 'y_bus1', 'country': 'country_bus1'}, inplace=True)


    # Get the props for the right ESC
    props = props.loc[ships.index[0]]
    
    # if export_esc == "shipping_lh2":

        # # Get the buses for 'berth (imp)' and 'berth (exp)'
        # berth_imp_buses = n.buses.filter(like='berth (imp)', axis=0)
        # berth_exp_buses = n.buses.filter(like='berth (exp)', axis=0)

        # # Get the index values for 'berth (imp)' and 'berth (exp)'
        # berth_imp_index = n.buses.filter(like='berth (imp)', axis=0).index.tolist()
        # berth_exp_index = n.buses.filter(like='berth (exp)', axis=0).index.tolist()

        # # Create all combinations
        # combinations = list(product(berth_exp_index, berth_imp_index))

        # # Create DataFrame
        # ships = pd.DataFrame(combinations, columns=['bus0', 'bus1'])

        # # Add 'name' column if necessary
        # ships['name'] = 'H2 (l) transport ship'

        # # Set 'name' as index
        # ships.set_index('name', inplace=True)

        # # Add a column for the combinatino of exp-imp ports
        # ships['combi'] = ships['bus0'].str.replace('berth \(exp\)', '', regex=True) +' --> '+ ships['bus1'].str.replace('berth \(imp\)', '', regex=True)

        # # Merge the ships DataFrame with the berth_exp_buses DataFrame based on the 'bus0' column
        # ships = pd.merge(ships, berth_exp_buses[['x', 'y', 'country']], left_on='bus0', right_index=True, how='left')

        # # Rename the columns to 'x_bus1' and 'y_bus1'
        # ships.rename(columns={'x': 'x_bus0', 'y': 'y_bus0', 'country': 'country_bus0'}, inplace=True)

        # # Merge the ships DataFrame with the berth_imp_buses DataFrame based on the 'bus1' column
        # ships = pd.merge(ships, berth_imp_buses[['x', 'y', 'country']], left_on='bus1', right_index=True, how='left')

        # # Rename the columns to 'x_bus1' and 'y_bus1'
        # ships.rename(columns={'x': 'x_bus1', 'y': 'y_bus1', 'country': 'country_bus1'}, inplace=True)


        # # Get the props for the right ESC
        # props = props.loc[ships.index[0]]


    shipping_routes = pd.DataFrame()

    for j in range(len(ships)):
        ship = ships.iloc[j]
        combi = ship['combi']


        loading_time = int(np.floor(props.loc["(un-) loading time", "value"]))
        unloading_time = loading_time
        loading_rate_pu = 1.0 / loading_time
        unloading_rate_pu = loading_rate_pu

        # Get the shipping route from Searoutes
        route = get_shipping_distance(ship)
        # Extract the distance
        distance =  route['length'][0]

        # Append the route DataFrame to the shipping_routes DataFrame
        shipping_routes = pd.concat([shipping_routes, route], ignore_index=True)

        # Travel time
        travel_time = int(np.ceil(distance / props.loc["average speed", "value"]))

        # Round trip time for a convoy (loading, travel, unloading, return trip)
        round_trip_time = loading_time + travel_time + unloading_time + travel_time

        # Number of full journeys (round-trip-journey) possible for convoy along sea route
        journeys = int(np.floor(n.snapshots.shape[0] / round_trip_time))

        if journeys == 0:
            logger.error(
                f"Please use a higher time resolution in config for ['scenario']['sopts'] in order to result in enough snapshots for a ship round trip. Currently it results only in {n.snapshots.shape[0]} snapshots for a round trip time of {round_trip_time}"
            )

        # By constructing the tightest shipping schedule starting at the beginning of the year
        # we have this amount of hours were the importing habour is not served...
        annual_shipping_gap = n.snapshots.shape[0] % round_trip_time

        # ... as we later construct additional shipping convoys by simply shifting the schedule,
        # this will create a nasty gap in the supply chain, resulting in weired results in the optimisation.
        # We avoid this by smoothing the supply: the shipping duration is artificially prolonged to reduce this gap
        # Can be thought of as something like a buffer, which is near identically distributed across all journeys
        additional_forward_travel_time = int(np.floor(annual_shipping_gap / journeys / 2))
        # return trip can take a bit longer (max 1 additional snapshot)
        additional_return_travel_time = int(
            np.floor(annual_shipping_gap / journeys - additional_forward_travel_time)
        )

        forward_travel_time = travel_time + additional_forward_travel_time
        return_travel_time = travel_time + additional_return_travel_time

        updated_round_trip_time = (
            loading_time + forward_travel_time + unloading_time + return_travel_time
        )
        logger.info(
            f"Increasing the round-trip travel time from {round_trip_time}h to "
            f"{updated_round_trip_time}h (+{(updated_round_trip_time/round_trip_time-1)*100:.2f}%) "
            f"to achieve more levelled supply by ship."
        )

        # One round-trip loading schedule for earliest convoy in year
        loading_schedule = np.concatenate(
            (
                [loading_rate_pu] * loading_time,
                [0] * forward_travel_time,
                [0] * unloading_time,
                [0] * return_travel_time,
            )
        )

        # One round-trip unloading schedule for earliest convoy in year
        unloading_schedule = np.concatenate(
            (
                [0] * loading_time,
                [0] * forward_travel_time,
                [unloading_rate_pu] * unloading_time,
                [0] * return_travel_time,
            )
        )

        # Numbers of convoys (base convoy + convoys which can be loaded without competing for the
        #  loading infrastructure while the base convoy is on its way)
        # if loading_time == unloading_time there this approach results in no clashes for the unloading infrastruct.
        convoy_number = 1 + int(
            np.floor(
                (forward_travel_time + return_travel_time + unloading_time) / loading_time
            )
        )

        shift = (forward_travel_time + unloading_time + return_travel_time) % unloading_time
        shift_per_convoy = int(np.floor(shift / convoy_number))

        # Create full year schedule for loading:
        # Left-over days at end of year (which can not be used for a full round-trip journey)
        # are filled with 0s (=no journey/anchored)
        loading_schedule = np.concatenate([loading_schedule] * journeys)
        tmp = np.zeros(n.snapshots.shape[0])
        tmp[: loading_schedule.shape[0]] = loading_schedule
        loading_schedule = tmp

        # Create full year schedule for unloading:
        # (Basically the same as for loading, could use np.roll here as rates and durations for loading
        #  and unloading are identical in the current model version)
        # Left-over days at end of year (which can not be used for a full round-trip journey)
        # are filled with 0s (=no journey/anchored)
        unloading_schedule = np.concatenate([unloading_schedule] * journeys)
        tmp = np.zeros(n.snapshots.shape[0])
        tmp[: unloading_schedule.shape[0]] = unloading_schedule
        unloading_schedule = tmp

        ## How the schedules look like
        # plt.plot(loading_schedule, label='loading')
        # plt.plot(unloading_schedule, label='unloading')
        # plt.legend()

        # Calculate energy transport efficiency for the trip

        # Boil-off losses are only considered for the outward journey.
        # technically the cargo hold should be kept at cryo temperatures and uncontaminated also during
        # the inward journey. Neglect boil-off during inward journey here, as this can be expected to be
        # significantly smaller than the onboard energy demand (all boil-off is certainly consumed by energy demand)
        boil_off = (1 - props.loc["boil-off", "value"] / 100) ** forward_travel_time

        # losses from ship propulsion (outward and return journey)
        energy_demand = (
            1
            - 2
            * distance
            * props.loc["energy demand", "value"]
            / props.loc["capacity", "value"]
        )
        # take whatever requires more energy (boil-off can be used by propulsion or propulsion uses cargo)
        shipping_efficiency = np.min([energy_demand, boil_off])

        # Additional energy losses from (un-) loading the cargo
        loading_efficiency = 1 - props.loc["(un-) loading losses", "value"] / 100
        unloading_efficiency = loading_efficiency

        # Calculate investment costs per gross MWh capacity
        # wacc = pd.read_csv(snakemake.input["wacc"], comment="#", index_col="region")
        # wacc = wacc.loc[snakemake.wildcards["from"], scenario["wacc"]]
        wacc = dr
        # wacc *= yaml_content["export"]["esc_scenarios"]["default"]["modifiers"]  # Apply scenario modifier

        costs = pd.read_csv(costs_path, index_col=["technology", "parameter"])
        costs = costs.loc[ship.name]

        # Consistency check: whether units match
        unit_costs = costs.loc["capacity"]["unit"]
        unit_bus = n.buses.loc[ship["bus0"]]["unit"]
        if unit_costs.startswith(unit_bus) is False:
            raise ValueError(
                f"Unit mismatch for shipping capacity between network ({unit_bus}) "
                f"and cost database ({unit_costs})."
            )

        try:
            capital_cost = calculate_annuity(
                costs.loc["investment", "value"],
                costs.loc["FOM", "value"],
                costs.loc["lifetime", "value"],
                wacc,
            )
            capital_cost /= costs.loc["capacity", "value"]
        except:
            raise ValueError(
                f"Exception calculating capital cost for {ship.name}."
                f"Missing cost or shipping property entries"
            )

        if distance == 0:
            # Treat the special case, where distance between exporter and importer is zero.
            # (e.g. same exporter as importer region)

            logger.info(
                f"No distance between exporter and importer. "
                f"Adding a direct pseudo connection without shipping schedule."
            )

            convoy_number = 1

            loading_schedule = np.ones(n.snapshots.shape[0])
            unloading_schedule = loading_schedule

        else:
            logger.info(f"Adding {convoy_number} shipping convoys to shipping route.")

        for i in range(convoy_number):

            ship_bus = f"{ship.name} convoy {i+1} - {combi}"

            n.add(
                "Bus",
                name=f"{ship_bus} (exp)",
                carrier=n.buses.loc[ship.loc["bus0"], "carrier"],
                unit=n.buses.loc[ship.loc["bus0"], "unit"],
            )

            n.add(
                "Link",
                name=f"{ship_bus} loading",
                bus0=ship.loc["bus0"],
                bus1=f"{ship_bus} (exp)",
                efficiency=loading_efficiency,
                # Capacity expansion at point of export/depature
                # ship capacity taken into account as gross capacity before transport losses/demand
                p_nom_extendable=True,
                # Loading extracts energy from bus and happens at max rate and at fixed times
                # Rolling the schedules ensures there is no overlap between convoys
                p_min_pu=np.roll(
                    loading_schedule, i * (loading_time + shift_per_convoy)
                ),  # np.zeros_like(loading_schedule),
                # p_min_pu=0.0,
                p_max_pu=np.roll(loading_schedule, i * (loading_time + shift_per_convoy)),
            )

            n.add(
                "Store",
                name=f"{ship_bus} cargo (exp)",
                bus=f"{ship_bus} (exp)",
                e_nom_extendable=True,
                # Ships may be starting at end of year and start deliver at the beginning of the year
                e_cyclic=True,
                # Full capital cost of the ship
                capital_cost=capital_cost,
                # Additions that are not in TRACE
                e_nom_min=costs.loc["capacity", "value"] * yaml_content["export"]["esc_scenarios"]["minimum_convoy_cap"],
                e_nom_max=costs.loc["capacity", "value"] * yaml_content["export"]["esc_scenarios"]["maximum_convoy_cap"],
                # e_nom_mod=costs.loc["capacity", "value"],
                lifetime=costs.loc["lifetime", "value"],
            )

            n.add(
                "Bus",
                name=f"{ship_bus} (imp)",
                carrier=n.buses.loc[ship.loc["bus0"], "carrier"],
                unit=n.buses.loc[ship.loc["bus0"], "unit"],
            )

            n.add(
                "Link",
                name=f"{ship_bus} unloading",
                bus0=f"{ship_bus} (imp)",
                bus1=ship.loc["bus1"],
                efficiency=unloading_efficiency,
                p_nom_extendable=True,
                # Unloading at max rate and at fixed times
                # Rolling the schedules ensures there is no overlap between convoys
                p_min_pu=np.roll(
                    unloading_schedule, i * (unloading_time + shift_per_convoy)
                ),  # np.zeros_like(unloading_schedule),
                # p_min_pu=0.0,
                p_max_pu=np.roll(
                    unloading_schedule, i * (unloading_time + shift_per_convoy)
                ),
            )

            n.add(
                "Link",
                name=f"{ship_bus} trip demand & losses",
                bus0=f"{ship_bus} (exp)",
                bus1=f"{ship_bus} (imp)",
                efficiency=shipping_efficiency,
                p_nom_extendable=True,
            )

            # Special case LOHC:
            # requires a return channel for unloaded LOHC using the same ship and thus a dedicated store component
            # Warning: Partially hardcoded!
            # Note: Relies on information from ships.csv
            # Note: Linked to a extra_functionality in solve_network.py.ipynb fixing the two store's capacities
            if n.name == "LOHC shipping":

                n.add(
                    "Bus",
                    name=f"{ship_bus} LOHC (used)",
                    carrier=n.buses.loc["LOHC (used) (exp)", "carrier"],
                    unit=n.buses.loc["LOHC (used) (exp)", "unit"],
                )

                n.add(
                    "Store",
                    name=f"{ship_bus} cargo LOHC (used)",
                    bus=f"{ship_bus} LOHC (used)",
                    e_nom_extendable=True,
                    e_cyclic=True,
                    # Capital costs already considered by the cargo store for loaded LOHC
                    capital_cost=0,
                )

                n.add(
                    "Link",
                    name=f"{ship_bus} LOHC (used) loading",
                    bus0=ships.loc["LOHC (used) transport ship", "bus0"],
                    bus1=f"{ship_bus} LOHC (used)",
                    efficiency=1.0,
                    p_nom_extendable=True,
                    # Loading extracts energy from bus and happens at max rate and at fixed times
                    # Rolling the schedules ensures there is no overlap between convoys
                    p_min_pu=np.roll(
                        unloading_schedule, i * (unloading_time + shift_per_convoy)
                    ),  # np.zeros_like(unloading_schedule),
                    p_max_pu=np.roll(
                        unloading_schedule, i * (unloading_time + shift_per_convoy)
                    ),
                )

                n.add(
                    "Link",
                    name=f"{ship_bus} LOHC (used) unloading",
                    bus0=f"{ship_bus} LOHC (used)",
                    bus1=ships.loc["LOHC (used) transport ship", "bus1"],
                    efficiency=1.0,
                    p_nom_extendable=True,
                    # Unloading at max rate and at fixed times
                    # Rolling the schedules ensures there is no overlap between convoys
                    p_min_pu=np.roll(
                        loading_schedule, i * (loading_time + shift_per_convoy)
                    ),  # np.zeros_like(loading_schedule),
                    p_max_pu=np.roll(
                        loading_schedule, i * (loading_time + shift_per_convoy)
                    ),
                )

                # Ratio LOHC / H2 in loaded LOHC
                loaded_unloaded_ratio = read_efficiencies(
                    efficiencies_path, yaml_content["scenario"]["planning_horizons"]
                )
                loaded_unloaded_ratio = loaded_unloaded_ratio.loc[
                    (loaded_unloaded_ratio["process"] == "LOHC dehydrogenation")
                    & (loaded_unloaded_ratio["from"] == "LOHC (loaded)")
                    & (loaded_unloaded_ratio["to"] == "LOHC (used)")
                ]["efficiency"].item()
                n.links.loc[
                    f"{ship_bus} trip demand & losses", "bus2"
                ] = f"{ship_bus} LOHC (used)"
                n.links.loc[f"{ship_bus} trip demand & losses", "efficiency2"] = (
                    1 - shipping_efficiency
                ) * loaded_unloaded_ratio
    return n


def create_esc_network(n, nodes, exp_nodes, imp_nodes, exp_ports, export_esc, import_profile, import_ports, nodes_df, yaml_content, efficiencies, costs):
    """Create the pypsa network scaffolding for the ESC."""

    # Load import country boundary
    world = gpd.read_file(gpd.datasets.get_path('naturalearth_lowres'))

    world['iso_2'] = world['iso_a3'].apply(lambda x: three_2_two_digits_country(x))

    # Filter out the import_country with ISO 3166-1 alpha-2 code 
    import_country = world[world['iso_2'] == import_ports.country[0]]

    # Reproject to EPSG:4326
    target_crs = "EPSG:4326" # WGS84 
    import_country = import_country.to_crs(target_crs)

    # Calculate the centroid
    import_country_centroid = import_country.centroid

    # Get coordinates of the centroids
    x_import = import_country_centroid.x
    y_import = import_country_centroid.y


    #----------------
    # Liquid Hydrogen 
    #----------------
    if export_esc == "shipping_lh2":
        logger.info("Adding Export Supply Chain: " + export_esc)
        add_shipping_lh2(n, exp_nodes, imp_nodes, exp_ports, import_profile, x_import, y_import, yaml_content, import_ports, efficiencies, costs)
    #----------------
    # Liquid Ammonia 
    #----------------
    elif export_esc == "shipping_lnh3":
        logger.info("Adding Export Supply Chain: " + export_esc)
        add_shipping_lnh3(n, nodes, nodes_df, exp_nodes, imp_nodes, exp_ports, import_profile, x_import, y_import, yaml_content, import_ports, efficiencies, costs)
        # add_shipping_lnh3_old(n, nodes, nodes_df, exp_nodes, imp_nodes, exp_ports, import_profile, x_import, y_import)
    #----------------
    # Methanol (MeOH) 
    #----------------
    elif export_esc == "shipping_meoh":
        logger.info("Adding Export Supply Chain: " + export_esc)
        add_shipping_meoh(n, nodes, nodes_df, exp_nodes, imp_nodes, exp_ports, import_profile, x_import, y_import, yaml_content, import_ports, efficiencies, costs)




def prepare_network(n, solve_opts=None):
    # if snakemake.config["rescale_emissions"]:
    #     pass
    # n.carriers.co2_emissions = n.carriers.co2_emissions * 1e-6
    # n.global_constraints.at["CO2Limit", "constant"] = n.global_constraints.at["CO2Limit", "constant"] * 1e-6
    if "lv_limit" in n.global_constraints.index:
        n.line_volume_limit = n.global_constraints.at["lv_limit", "constant"]
        n.line_volume_limit_dual = n.global_constraints.at["lv_limit", "mu"]

    if "clip_p_max_pu" in solve_opts:
        for df in (
            n.generators_t.p_max_pu,
            n.generators_t.p_min_pu,
            n.storage_units_t.inflow,
        ):
            df.where(df > solve_opts["clip_p_max_pu"], other=0.0, inplace=True)

    if solve_opts.get("load_shedding"):
        n.add("Carrier", "Load")
        n.madd(
            "Generator",
            n.buses.index,
            " load",
            bus=n.buses.index,
            carrier="load",
            sign=1e-3,  # Adjust sign to measure p and p_nom in kW instead of MW
            marginal_cost=1e2,  # Eur/kWh
            # intersect between macroeconomic and surveybased
            # willingness to pay
            # http://journal.frontiersin.org/article/10.3389/fenrg.2015.00055/full
            p_nom=1e9,  # kW
        )

    if solve_opts.get("noisy_costs"):
        for t in n.iterate_components():
            # if 'capital_cost' in t.df:
            #    t.df['capital_cost'] += 1e1 + 2.*(np.random.random(len(t.df)) - 0.5)
            if "marginal_cost" in t.df:
                np.random.seed(174)
                t.df["marginal_cost"] += 1e-2 + 2e-3 * (
                    np.random.random(len(t.df)) - 0.5
                )

        for t in n.iterate_components(["Line", "Link"]):
            np.random.seed(123)
            t.df["capital_cost"] += (
                1e-1 + 2e-2 * (np.random.random(len(t.df)) - 0.5)
            ) * t.df["length"]

    if solve_opts.get("nhours"):
        nhours = solve_opts["nhours"]
        n.set_snapshots(n.snapshots[:nhours])
        n.snapshot_weightings[:] = 8760.0 / nhours

    return n



def add_nh3_store_cap(n, cap):
    nh3_stores = n.stores.loc[(n.stores.carrier == "NH3 store")]
    if nh3_stores.index.empty or ("Store", "e_nom") not in n.variables.index:
        return
    nh3_stores_cap = get_var(n, "Store", "e_nom")
    subset_index = nh3_stores.index.intersection(nh3_stores.index)
    diff_index = nh3_stores_cap.index.difference(subset_index)
    # if len(diff_index) > 0:
    #     logger.warning(
    #         f"Impossible to set NH3 store cap for the following stores: {diff_index}"
    #     )
    lhs = linexpr(
        (1, nh3_stores_cap[subset_index])
    ).sum()
    # lhs = linexpr((1, h2_network_cap[h2_network.index])).sum()
    rhs = cap * 1000
    define_constraints(n, lhs, "<=", rhs, "nh3_stores_cap")



def add_battery_constraints(n):
    chargers_b = n.links.carrier.str.contains("battery charger")
    chargers = n.links.index[chargers_b & n.links.p_nom_extendable]
    dischargers = chargers.str.replace("charger", "discharger")

    if chargers.empty or ("Link", "p_nom") not in n.variables.index:
        return

    link_p_nom = get_var(n, "Link", "p_nom")

    lhs = linexpr(
        (1, link_p_nom[chargers]),
        (
            -n.links.loc[dischargers, "efficiency"].values,
            link_p_nom[dischargers].values,
        ),
    )

    define_constraints(n, lhs, "=", 0, "Link", "charger_ratio")



def extra_functionality(n, yaml_content):
    add_battery_constraints(n)

    # if yaml_content["export"]["esc_scenarios"]["synthesis"] == 'free': # TODO change it to snakemake.config["sector"]["ammonia"]["network"] if necessary in the future
    if yaml_content["sector"]["ammonia"]["storage_limit"]:
        add_nh3_store_cap(
            n, yaml_content["sector"]["ammonia"]["storage_limit"]
        )


def solve_network(n, config, yaml_content, opts="", **kwargs):
    solver_options = config["solving"]["solver"].copy()
    solver_name = solver_options.pop("name")
    cf_solving = config["solving"]["options"]
    track_iterations = cf_solving.get("track_iterations", False)
    min_iterations = cf_solving.get("min_iterations", 4)
    max_iterations = cf_solving.get("max_iterations", 6)

    # add to network for extra_functionality
    n.config = config
    n.opts = opts

    if cf_solving.get("skip_iterations", False):
        network_lopf(
            n,
            solver_name=solver_name,
            solver_options=solver_options,
            extra_functionality=lambda n, snapshots: extra_functionality(n, yaml_content),
            **kwargs,
        )
    else:
        ilopf(
            n,
            solver_name=solver_name,
            solver_options=solver_options,
            track_iterations=track_iterations,
            min_iterations=min_iterations,
            max_iterations=max_iterations,
            extra_functionality=extra_functionality,
            **kwargs,
        )
    return n