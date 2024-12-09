# -*- coding: utf-8 -*-
"""
Proposed code structure:
X read network (.nc-file)
X add export bus
X connect hydrogen buses (advanced: only ports, not all) to export bus
X add esc
X add load

Possible improvements:
- Select port buses automatically (with both voronoi and gadm clustering). Use data/ports.csv?
"""


import logging
import os
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pypsa
import searoute as sr
from shapely.geometry import LineString
from itertools import product
from helpers import (locate_bus, override_component_attrs, prepare_costs, 
                    calculate_annual_investment, calculate_annuity,
                    configure_logging, extract_technology, get_bus_unit,
                    read_efficiencies, three_2_two_digits_country, lossy_bidirectional_links)


logger = logging.getLogger(__name__)


def _do_units_match(unit1, unit2):
    """Rough checker if two units match.

    Catches mismatches between e.g. t, m^3 and W.
    Does not catch order of magnitude mismatches by SI prefixes."""

    def _stripper(u):
        import re

        # remove optional Si prefixes 'M', 'k' and per hour ('/h', 'h') indicators
        u = re.match("[Mk]?(.+?)\/?h?$", re.split("_|-", u)[0]).groups()[0]

        # Specific indicators to remove, a bit hacky and may cause problems they do not match. Hotfix.
        for p in ["CO2", "/km"]:
            u = u.replace(p, "")

        return u

    return _stripper(unit1) == _stripper(unit2)



# def get_shipping_distances(exp_ports, import_ports):

#     # Define a function to parse the JSON data and create a GeoDataFrame
#     def parse_json_to_geodataframe(json_data):
#         # Extract geometry coordinates
#         coordinates = json_data['geometry']['coordinates']
        
#         # Create LineString geometry
#         geometry = LineString(coordinates)
        
#         # Extract properties
#         properties = json_data['properties']
        
#         # Create a dictionary for GeoDataFrame construction
#         data = {
#             'port_origin_cty': [properties['port_origin']['cty']],
#             'port_origin_name': [properties['port_origin']['name']],
#             'port_origin_port': [properties['port_origin']['port']],
#             'port_origin_t': [properties['port_origin']['t']],
#             'port_origin_x': [properties['port_origin']['x']],
#             'port_origin_y': [properties['port_origin']['y']],
#             'port_dest_cty': [properties['port_dest']['cty']],
#             'port_dest_name': [properties['port_dest']['name']],
#             'port_dest_port': [properties['port_dest']['port']],
#             'port_dest_t': [properties['port_dest']['t']],
#             'port_dest_x': [properties['port_dest']['x']],
#             'port_dest_y': [properties['port_dest']['y']],
#             'length': [properties['length']],
#             'units': [properties['units']],
#             'duration_hours': [properties['duration_hours']],
#             'geometry': [geometry],
#         }
        
#         # Create GeoDataFrame
#         gdf = gpd.GeoDataFrame(data)
        
#         # Set CRS
#         gdf.crs = 'EPSG:4326'  # WGS84
        
#         return gdf

#     # origin = [33.416254900844, 44.5855065767527]
#     # destination = [-2.92229843, 35.2748795]

#     # route = sr.searoute(origin, destination, append_orig_dest=True, restrictions=['northwest'], include_ports=True, port_params={'only_terminals':True, 'country_pol': 'UA', 'country_pod' :'MA'})

#     # # Parse the JSON data and create a GeoDataFrame
#     # gdf = parse_json_to_geodataframe(route)


#     routes = pd.DataFrame()
    
#     for _, export_row in exp_ports.iterrows():
#         export_x = export_row['x']
#         export_y = export_row['y']
#         export_country = export_row['country']

#         for _, import_row in import_ports.iterrows():
#             import_x = import_row['x']
#             import_y = import_row['y']
#             import_country = import_row['country']

#             origin = [export_x, export_y]
#             destination = [import_x, import_y]

#             # route = sr.searoute(origin, destination, append_orig_dest=True, restrictions=['northwest'], include_ports=True, port_params={'only_terminals':True, 'country_pol': export_country, 'country_pod' :import_country})
#             route = sr.searoute(origin, destination, append_orig_dest=True, restrictions=['northwest'], include_ports=True, port_params={ 'country_pol': export_country, 'country_pod' :import_country})

#             # Parse the JSON data and create a GeoDataFrame
#             route = parse_json_to_geodataframe(route)

#             # # Append the route to the routes list
#             # routes.append(route)

#             # Append the route DataFrame to the concatenated_routes DataFrame
#             routes = pd.concat([routes, route], ignore_index=True)

#     return routes


# Define a function to parse the JSON data and create a GeoDataFrame
def parse_json_to_geodataframe(json_data, ship):
    # Extract geometry coordinates
    coordinates = json_data['geometry']['coordinates']
    
    # Create LineString geometry
    geometry = LineString(coordinates)
    
    # Extract properties
    properties = json_data['properties']
    
    # Create a dictionary for GeoDataFrame construction
    data = {
        'port_origin_cty': [properties['port_origin']['cty']],
        'port_origin_name': [properties['port_origin']['name']],
        'port_origin_port': [properties['port_origin']['port']],
        'port_origin_t': [properties['port_origin']['t']],
        'port_origin_x': [properties['port_origin']['x']],
        'port_origin_y': [properties['port_origin']['y']],
        'port_dest_cty': [properties['port_dest']['cty']],
        'port_dest_name': [properties['port_dest']['name']],
        'port_dest_port': [properties['port_dest']['port']],
        'port_dest_t': [properties['port_dest']['t']],
        'port_dest_x': [properties['port_dest']['x']],
        'port_dest_y': [properties['port_dest']['y']],
        'length': [properties['length']],
        'units': [properties['units']],
        'duration_hours': [properties['duration_hours']],
        'geometry': [geometry],
    }
    
    # Create GeoDataFrame
    gdf = gpd.GeoDataFrame(data)
    
    # Set CRS
    gdf.crs = 'EPSG:4326'  # WGS84

    gdf['bus0'] = ship['bus0']
    gdf['bus1'] = ship['bus1']
    
    return gdf



def get_shipping_distance(ship):
    origin = [ship['x_bus0'], ship['y_bus0']]
    destination = [ship['x_bus1'], ship['y_bus1']]

    route = sr.searoute(origin, destination, append_orig_dest=True, restrictions=['northwest'], include_ports=True, port_params={'only_terminals':True, 'country_pol': ship['country_bus0'], 'country_pod' :ship['country_bus1']})

    # Parse the JSON data and create a GeoDataFrame
    gdf = parse_json_to_geodataframe(route, ship)

    return gdf


def select_ports(n):
    """This function selects the buses where ports are located"""

    ports = pd.read_csv(
        snakemake.input.export_ports,
        index_col=None,
        keep_default_na=False,
    ).squeeze()
    ports = ports[ports.country.isin(countries)]

    gadm_level = snakemake.params.gadm_level

    ports["gadm_{}".format(gadm_level)] = ports[["x", "y", "country"]].apply(
        lambda port: locate_bus(
            port[["x", "y"]],
            port["country"],
            gadm_level,
            snakemake.input["shapes_path"],
            snakemake.params.clustering_options,
        ),
        axis=1,
    )

    ports = ports.set_index("gadm_{}".format(gadm_level))

    # Select the hydrogen buses based on nodes with ports
    hydrogen_buses_ports = n.buses.loc[ports.index + " H2"]
    hydrogen_buses_ports.index.name = "Bus"
    # hydrogen_buses_ports.loc[hydrogen_buses_ports.index, 'x'] = hydrogen_buses_ports.loc[hydrogen_buses_ports.index, 'x']

    return (hydrogen_buses_ports, ports)


# def add_prefixes(df, prefixes, hydrogen_buses_ports, import_ports, column_name):
#     # Filter rows where column_name contains "(exp)"
#     filtered_df = df[df[column_name].str.contains("\(exp\)")]

    

#     # Duplicate rows and add different prefixes
#     new_rows = []
#     for prefix in prefixes:
#         new_df = filtered_df.copy()  # Make a copy of the filtered DataFrame
#         new_df[column_name] = prefix + ' ' + new_df[column_name]  # Add prefix to the column values
#         new_rows.append(new_df)

#     # Filter rows where column_name contains "(imp)"
#     filtered_df_imp = df[df[column_name].str.contains("\(imp\)")]

#         # Duplicate rows and add different prefixes
#     for prefix in import_ports.name:
#         new_df = filtered_df_imp.copy()  # Make a copy of the filtered DataFrame
#         new_df[column_name] = prefix + ' ' + new_df[column_name]  # Add prefix to the column values
#         new_rows.append(new_df)

#     # Concatenate the new rows with the original DataFrame
#     final_df = pd.concat(new_rows, ignore_index=True)

#     return final_df


def get_efficiency(efficiencies, tech, src_bus, tar_bus):

    tech = extract_technology(tech)
    src = extract_technology(src_bus)
    tar = extract_technology(tar_bus)

    efficiency = efficiencies[
        (efficiencies["process"].str.contains(tech, regex=False))
        & (efficiencies["to"].str.contains(tar, regex=False))
        & (efficiencies["from"].str.contains(src, regex=False))
    ]

    if efficiency.empty is True:
        return np.nan

    # # Check if all units match
    # src_unit = get_bus_unit(src_bus, n)
    # tar_unit = get_bus_unit(tar_bus, n)
    # unit_mismatch = None
    # if (efficiency[["from_unit", "to_unit"]] == "p.u.").any(
    #     axis=None
    # ) == True:  #'==' b/c pd.any returns np.bool

    #     if (efficiency[["from_unit", "to_unit"]] == "p.u.").all(
    #         axis=None
    #     ) == False:  #'==' b/c pd.any returns np.bool
    #         unit_mismatch = "One efficiency in [p.u.], but the other one not."
    #     elif _do_units_match(src_unit, tar_unit) is False:
    #         unit_mismatch = f"Unit of bus {src_bus} [{src_unit}] does not match {tar_bus} [{tar_unit}]."

    # elif _do_units_match(src_unit, efficiency["from_unit"].item()) is False:
    #     unit_mismatch = (
    #         f"Source bus unit {src_bus} [{src_unit}] does not match unit "
    #         f'in registered efficiencies.csv [{efficiency["from_unit"].item()}].'
    #     )
    # elif _do_units_match(tar_unit, efficiency["to_unit"].item()) is False:
    #     unit_mismatch = (
    #         f"Target bus unit {tar_bus} [{tar_unit}] does not match unit "
    #         f'in registered efficiencies.csv [{efficiency["to_unit"].item()}].'
    #     )

    # if unit_mismatch:
    #     raise ValueError(f"Mismatching units for {tech}: {unit_mismatch}.")

    return efficiency["efficiency"].item()



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



def add_shipping_lnh3(n, nodes, nodes_df, exp_nodes, imp_nodes, exp_ports, import_profile, x_import, y_import):

    n.add("Carrier", "NH3", nice_name="Ammonia")
    n.add("Carrier", "NH3 store", nice_name="Ammonia storage")
    n.add("Carrier", "N2", nice_name="Nitrogen")

    if snakemake.params.synthesis == "at_port":
        nodes = exp_nodes
        nodes_df = exp_ports

    # Buses: shipping_lnh3 (Liquid Ammonia)
    n.madd("Bus", nodes, suffix=" NH3 (g)", carrier="NH3", location=nodes, unit="MW", x=nodes_df.x, y=nodes_df.y, country=nodes_df.country.iloc[0]),
    n.madd("Bus", nodes, suffix=" NH3 (l)", carrier="NH3 store", location=nodes, unit="MW", x=nodes_df.x, y=nodes_df.y, country=nodes_df.country.iloc[0]),
    n.madd("Bus", imp_nodes, suffix=" NH3 (l) (imp)", carrier="NH3 store imp", location=imp_nodes, unit="MW", x=import_ports.x, y=import_ports.y, country=import_ports.country.iloc[0]),
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

    if snakemake.params.synthesis == "free":

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
            terrain_factor=snakemake.params.terrain_factor_pipeline,
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

    n.add("Carrier", "meOH", nice_name="Methanol", co2_emissions=costs.at["methanol", "CO2 intensity"])
    n.add("Carrier", "DAC for meOH", nice_name="Direct Air Capture for Methanol")
    

    if snakemake.params.synthesis == "at_port":
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


    if snakemake.params.synthesis == "free":

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










def create_esc_network(n, nodes, exp_nodes, imp_nodes, exp_ports, export_esc, import_profile, import_ports, nodes_df):
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
        add_shipping_lh2(n, exp_nodes, imp_nodes, exp_ports, import_profile, x_import, y_import)
    #----------------
    # Liquid Ammonia 
    #----------------
    elif export_esc == "shipping_lnh3":
        logger.info("Adding Export Supply Chain: " + export_esc)
        add_shipping_lnh3(n, nodes, nodes_df, exp_nodes, imp_nodes, exp_ports, import_profile, x_import, y_import)
        # add_shipping_lnh3_old(n, nodes, nodes_df, exp_nodes, imp_nodes, exp_ports, import_profile, x_import, y_import)
    #----------------
    # Methanol (MeOH) 
    #----------------
    elif export_esc == "shipping_meoh":
        logger.info("Adding Export Supply Chain: " + export_esc)
        add_shipping_meoh(n, nodes, nodes_df, exp_nodes, imp_nodes, exp_ports, import_profile, x_import, y_import)



def add_esc_shipping(n):
    """Adds optional shipping routes to the network.

    Checks whether shipping for the wildcard "ESC" exists and - if it does - constructs
    a shipping route with multiple convoys (as optimisation options) for this route
    using standard PyPSA components.

    """
    
    props = pd.read_csv(
        snakemake.input["shipping_properties"],
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
        wacc = eval(snakemake.wildcards["discountrate"])
        wacc *= snakemake.params.modifiers_wacc  # Apply scenario modifier

        costs = pd.read_csv(snakemake.input["costs"], index_col=["technology", "parameter"])
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
                e_nom_min=costs.loc["capacity", "value"] * snakemake.params.minimum_convoy_cap,
                e_nom_max=costs.loc["capacity", "value"] * snakemake.params.maximum_convoy_cap,
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
                    snakemake.input["efficiencies"], snakemake.wildcards["planning_horizons"]
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





def add_export(n, hydrogen_buses_ports, export_profile):
    country_shape = gpd.read_file(snakemake.input["shapes_path"])
    # Find most northwestern point in country shape and get x and y coordinates
    country_shape = country_shape.to_crs(
        "EPSG:3395"
    )  # Project to Mercator projection (Projected)

    # Get coordinates of the most western and northern point of the country and add a buffer of 2 degrees (equiv. to approx 220 km)
    x_export = country_shape.geometry.centroid.x.min() - 2
    y_export = country_shape.geometry.centroid.y.max() + 2

    # add export bus
    n.add(
        "Bus",
        "H2 export bus",
        carrier="H2",
        x=x_export,
        y=y_export,
    )

    # add export links
    logger.info("Adding export links")
    n.madd(
        "Link",
        names=hydrogen_buses_ports.index + " export",
        bus0=hydrogen_buses_ports.index,
        bus1="H2 export bus",
        p_nom_extendable=True,
    )

    export_links = n.links[n.links.index.str.contains("export")]
    logger.info(export_links)

    # add store depending on config settings

    if snakemake.params.export_store == True:
        if snakemake.params.store_costs == "no_costs":
            capital_cost = 0
        elif snakemake.params.store_costs == "standard_costs":
            capital_cost = costs.at[
                "hydrogen storage tank type 1 including compressor", "fixed"
            ]
        else:
            logger.error(
                f"Value {snakemake.params.store_costs} for ['export']['store_capital_costs'] is not valid"
            )

        n.add(
            "Store",
            "H2 export store",
            bus="H2 export bus",
            e_nom_extendable=True,
            carrier="H2",
            e_initial=0,  # actually not required, since e_cyclic=True
            marginal_cost=0,
            capital_cost=capital_cost,
            e_cyclic=True,
        )

    elif snakemake.params.export_store == False:
        pass

    # add load
    n.add(
        "Load",
        "H2 export load",
        bus="H2 export bus",
        carrier="H2",
        p_set=export_profile,
    )

    return


def create_export_profile():
    """This function creates the export profile based on the annual export demand and resamples it to temp resolution obtained from the wildcard"""

    export_h2 = eval(snakemake.wildcards["h2export"]) * 1e6  # convert TWh to MWh

    if snakemake.params.export_profile == "constant":
        export_profile = export_h2 / 8760
        snapshots = pd.date_range(freq="h", **snakemake.params.snapshots)
        export_profile = pd.Series(export_profile, index=snapshots)

    elif snakemake.params.export_profile == "ship":
        # Import hydrogen export ship profile and check if it matches the export demand obtained from the wildcard
        export_profile = pd.read_csv(snakemake.input.ship_profile, index_col=0)
        export_profile.index = pd.to_datetime(export_profile.index)
        export_profile = pd.Series(
            export_profile["profile"], index=pd.to_datetime(export_profile.index)
        )

        if np.abs(export_profile.sum() - export_h2) > 1:  # Threshold of 1 MWh
            logger.error(
                f"Sum of ship profile ({export_profile.sum()/1e6} TWh) does not match export demand ({export_h2} TWh)"
            )
            raise ValueError(
                f"Sum of ship profile ({export_profile.sum()/1e6} TWh) does not match export demand ({export_h2} TWh)"
            )

    # Resample to temporal resolution defined in wildcard "sopts" with pandas resample
    sopts = snakemake.wildcards.sopts.split("-")
    export_profile = export_profile.resample(sopts[0].casefold()).mean()

    # revise logger msg
    export_type = snakemake.params.export_profile
    logger.info(
        f"The yearly export demand is {export_h2/1e6} TWh, profile generated based on {export_type} method and resampled to {sopts[0]}"
    )

    return export_profile


def create_import_profile():
    """This function creates the import profile based on the annual export demand and resamples it to temp resolution obtained from the wildcard"""

    export_h2 = eval(snakemake.wildcards["h2export"]) * 1e6  # convert TWh to MWh

    if (snakemake.params.export_profile == "esc_scenarios") and (snakemake.params.import_profile == "constant"):
        import_profile = export_h2 / 8760
        # frequency = snakemake.config["scenario"]["sopts"].lower()
        # snapshots = pd.date_range(freq=frequency, **snakemake.params.snapshots)
        snapshots = pd.date_range(freq="h", **snakemake.params.snapshots)
        import_profile = pd.Series(import_profile, index=snapshots)

    elif (snakemake.params.export_profile == "esc_scenarios") and (snakemake.params.import_profile == "esc_profile"):
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
    sopts = snakemake.wildcards.sopts.split("-")

    import_profile = import_profile.resample(sopts[0].casefold()).mean()

    # revise logger msg
    export_type = snakemake.params.export_profile
    logger.info(
        f"The yearly import demand is {export_h2/1e6} TWh, profile generated based on {export_type} method and resampled to {sopts[0]}"
    )

    return import_profile


if __name__ == "__main__":
    if "snakemake" not in globals():
        os.chdir(os.path.dirname(os.path.abspath(__file__)))
        from helpers import mock_snakemake, sets_path_to_root

        snakemake = mock_snakemake(
            "add_export_supply_chain",
            simpl="",
            clusters="370",
            ll="v1.1",
            opts="Co2L",
            planning_horizons="2050",
            sopts="3H",
            discountrate="0.091",
            demand="AP",
            h2export="10",
            esc="shipping_lnh3",
        )
        sets_path_to_root("pypsa-earth-sec")

    overrides = override_component_attrs(snakemake.input.overrides)
    n = pypsa.Network(snakemake.input.network, override_component_attrs=overrides)
    countries = list(n.buses.country.unique())


    # Create import profile
    import_profiles = create_import_profile()

    # Prepare the costs dataframe
    Nyears = n.snapshot_weightings.generators.sum() / 8760

    costs = prepare_costs(
        snakemake.input.costs,
        snakemake.params.USD_to_EUR,
        eval(snakemake.wildcards.discountrate),
        Nyears,
        snakemake.params.lifetime,
    )

    # Additional costs that are included in the workflow of https://github.com/PyPSA/technology-data/tree/00a8be6282afd5732dc2ad5b86659b9e6d4a9cb3
    # A PR can be opened in this regard.
    additional_costs_input = prepare_costs(
        snakemake.input.additional_costs,
        snakemake.params.USD_to_EUR,
        eval(snakemake.wildcards.discountrate),
        Nyears,
        snakemake.params.lifetime,
    )

    costs = pd.concat([costs, additional_costs_input], ignore_index=False)



    efficiencies = read_efficiencies(
        snakemake.input["efficiencies"], snakemake.wildcards["planning_horizons"]
    )


    # get hydrogen export buses/ports
    hydrogen_buses_ports = select_ports(n)[0]
    hydrogen_buses_ports.set_index('location', inplace=True)

    exp_ports = select_ports(n)[1]


    # List of ports electrictiy buses
    exp_nodes = hydrogen_buses_ports.index

    # List of all AC nodes
    nodes_df = n.buses[n.buses.carrier == "AC"]
    nodes = n.buses[n.buses.carrier == "AC"].index

    # Import ports and nodes
    import_ports = pd.read_csv(
        snakemake.input.import_ports,
        index_col=None,
        keep_default_na=False,
    )#.squeeze()

    import_ports.set_index('name', inplace=True)
    imp_nodes = import_ports.index

    # Get the shipping Distances between the import and export ports
    # get_shipping_distances(exp_ports, import_ports)

    # Export Supply Chain wildcard
    export_esc = snakemake.wildcards["esc"]

    # add export value and components to network
    create_esc_network(n, nodes, exp_nodes, imp_nodes, exp_ports, export_esc, import_profiles, import_ports, nodes_df)

    for k, v in snakemake.config["sector"]["transmission_efficiency"].items():
        if k == "NH3 pipeline":
            lossy_bidirectional_links(n, k, v)



    add_esc_shipping(n)
    # add_export(n, hydrogen_buses_ports, export_profile)

    n.export_to_netcdf(snakemake.output[0])

    logger.info("Network successfully exported")
