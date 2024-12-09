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

logger = logging.getLogger(__name__)

# list of recognised nan values (NA and na excluded as may be confused with Namibia 2-letter country code)
NA_VALUES = ["NULL", "", "N/A", "NAN", "NaN", "nan", "Nan", "n/a", "null"]


def sets_path_to_root(root_directory_name):  # Imported from pypsa-africa
    """
    Search and sets path to the given root directory (root/path/file).

    Parameters
    ----------
    root_directory_name : str
        Name of the root directory.
    n : int
        Number of folders the function will check upwards/root directed.

    """
    import os

    repo_name = root_directory_name
    n = 8  # check max 8 levels above. Random default.
    n0 = n

    while n >= 0:
        n -= 1
        # if repo_name is current folder name, stop and set path
        if repo_name == os.path.basename(os.path.abspath(".")):
            repo_path = os.getcwd()  # os.getcwd() = current_path
            os.chdir(repo_path)  # change dir_path to repo_path
            print("This is the repository path: ", repo_path)
            print("Had to go %d folder(s) up." % (n0 - 1 - n))
            break
        # if repo_name NOT current folder name for 5 levels then stop
        if n == 0:
            print("Cant find the repo path.")
        # if repo_name NOT current folder name, go one dir higher
        else:
            upper_path = os.path.dirname(os.path.abspath("."))  # name of upper folder
            os.chdir(upper_path)


def mock_snakemake(rulename, **wildcards):
    """
    This function is expected to be executed from the 'scripts'-directory of '
    the snakemake project. It returns a snakemake.script.Snakemake object,
    based on the Snakefile.

    If a rule has wildcards, you have to specify them in **wildcards.

    Parameters
    ----------
    rulename: str
        name of the rule for which the snakemake object should be generated
    **wildcards:
        keyword arguments fixing the wildcards. Only necessary if wildcards are
        needed.
    """
    import os

    import snakemake as sm
    from pypsa.descriptors import Dict
    from snakemake.script import Snakemake

    script_dir = Path(__file__).parent.resolve()
    assert (
        Path.cwd().resolve() == script_dir
    ), f"mock_snakemake has to be run from the repository scripts directory {script_dir}"
    os.chdir(script_dir.parent)
    for p in sm.SNAKEFILE_CHOICES:
        if os.path.exists(p):
            snakefile = p
            break
    workflow = sm.Workflow(snakefile, overwrite_configfiles=[], rerun_triggers=[])
    # workflow = sm.Workflow(snakefile, overwrite_configfiles=[])
    workflow.include(snakefile)
    workflow.global_resources = {}
    rule = workflow.get_rule(rulename)
    dag = sm.dag.DAG(workflow, rules=[rule])
    wc = Dict(wildcards)
    job = sm.jobs.Job(rule, dag, wc)

    def make_accessable(*ios):
        for io in ios:
            for i in range(len(io)):
                io[i] = os.path.abspath(io[i])

    make_accessable(job.input, job.output, job.log)
    snakemake = Snakemake(
        job.input,
        job.output,
        job.params,
        job.wildcards,
        job.threads,
        job.resources,
        job.log,
        job.dag.workflow.config,
        job.rule.name,
        None,
    )
    # create log and output dir if not existent
    for path in list(snakemake.log) + list(snakemake.output):
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    os.chdir(script_dir)
    return snakemake


def prepare_costs(cost_file, USD_to_EUR, discount_rate, Nyears, lifetime):
    # set all asset costs and other parameters
    costs = pd.read_csv(cost_file, index_col=[0, 1]).sort_index()

    # correct units to MW and EUR
    costs.loc[costs.unit.str.contains("/kW"), "value"] *= 1e3
    costs.loc[costs.unit.str.contains("USD"), "value"] *= USD_to_EUR

    # min_count=1 is important to generate NaNs which are then filled by fillna
    costs = (
        costs.loc[:, "value"].unstack(level=1).groupby("technology").sum(min_count=1)
    )
    costs = costs.fillna(
        {
            "CO2 intensity": 0,
            "FOM": 0,
            "VOM": 0,
            "discount rate": discount_rate,
            "efficiency": 1,
            "fuel": 0,
            "investment": 0,
            "lifetime": lifetime,
        }
    )

    def annuity_factor(v):
        return annuity(v["lifetime"], v["discount rate"]) + v["FOM"] / 100

    costs["fixed"] = [
        annuity_factor(v) * v["investment"] * Nyears for i, v in costs.iterrows()
    ]

    return costs


def create_network_topology(
    n, prefix, like="ac", connector=" <-> ", bidirectional=True
):
    """
    Create a network topology like the power transmission network.

    Parameters
    ----------
    n : pypsa.Network
    prefix : str
    connector : str
    bidirectional : bool, default True
        True: one link for each connection
        False: one link for each connection and direction (back and forth)

    Returns
    -------
    pd.DataFrame with columns bus0, bus1 and length
    """

    ln_attrs = ["bus0", "bus1", "length"]
    lk_attrs = ["bus0", "bus1", "length", "underwater_fraction"]

    # TODO: temporary fix for whan underwater_fraction is not found
    if "underwater_fraction" not in n.links.columns:
        if n.links.empty:
            n.links["underwater_fraction"] = None
        else:
            n.links["underwater_fraction"] = 0.0

    candidates = pd.concat(
        [n.lines[ln_attrs], n.links.loc[n.links.carrier == "DC", lk_attrs]]
    ).fillna(0)

    positive_order = candidates.bus0 < candidates.bus1
    candidates_p = candidates[positive_order]
    swap_buses = {"bus0": "bus1", "bus1": "bus0"}
    candidates_n = candidates[~positive_order].rename(columns=swap_buses)
    candidates = pd.concat([candidates_p, candidates_n])

    def make_index(c):
        return prefix + c.bus0 + connector + c.bus1

    topo = candidates.groupby(["bus0", "bus1"], as_index=False).mean()
    topo.index = topo.apply(make_index, axis=1)

    if not bidirectional:
        topo_reverse = topo.copy()
        topo_reverse.rename(columns=swap_buses, inplace=True)
        topo_reverse.index = topo_reverse.apply(make_index, axis=1)
        topo = pd.concat([topo, topo_reverse])

    return topo


def create_dummy_data(n, sector, carriers):
    ind = n.buses_t.p.index
    ind = n.buses.index[n.buses.carrier == "AC"]

    if sector == "industry":
        col = [
            "electricity",
            "coal",
            "coke",
            "solid biomass",
            "methane",
            "hydrogen",
            "low-temperature heat",
            "naphtha",
            "process emission",
            "process emission from feedstock",
            "current electricity",
        ]
    else:
        raise Exception("sector not found")
    data = (
        np.random.randint(10, 500, size=(len(ind), len(col))) * 1000 * 1
    )  # TODO change 1 with temp. resolution

    return pd.DataFrame(data, index=ind, columns=col)


# def create_transport_data_dummy(pop_layout,
#                                 transport_data,
#                                 cars=4000000,
#                                 average_fuel_efficiency=0.7):

#     for country in pop_layout.ct.unique():

#         country_data = pd.DataFrame(
#             data=[[cars, average_fuel_efficiency]],
#             columns=transport_data.columns,
#             index=[country],
#         )
#         transport_data = pd.concat([transport_data, country_data], axis=0)

#     transport_data_dummy = transport_data

#     return transport_data_dummy

# def create_temperature_dummy(pop_layout, temperature):

#     temperature_dummy = pd.DataFrame(index=temperature.index)

#     for index in pop_layout.index:
#         temperature_dummy[index] = temperature["ES0 0"]

#     return temperature_dummy

# def create_energy_totals_dummy(pop_layout, energy_totals):
#     """
#     Function to add additional countries specified in pop_layout.index to energy_totals, these countries take the same values as Spain
#     """
#     # All countries in pop_layout get the same values as Spain
#     for country in pop_layout.ct.unique():
#         energy_totals.loc[country] = energy_totals.loc["ES"]

#     return energy_totals


def cycling_shift(df, steps=1):
    """Cyclic shift on index of pd.Series|pd.DataFrame by number of steps"""
    df = df.copy()
    new_index = np.roll(df.index, steps)
    df.values[:] = df.reindex(index=new_index).values
    return df


def override_component_attrs(directory):
    """Tell PyPSA that links can have multiple outputs by
    overriding the component_attrs. This can be done for
    as many buses as you need with format busi for i = 2,3,4,5,....
    See https://pypsa.org/doc/components.html#link-with-multiple-outputs-or-inputs

    Parameters
    ----------
    directory : string
        Folder where component attributes to override are stored
        analogous to ``pypsa/component_attrs``, e.g. `links.csv`.

    Returns
    -------
    Dictionary of overriden component attributes.
    """

    attrs = Dict({k: v.copy() for k, v in component_attrs.items()})

    for component, list_name in components.list_name.items():
        fn = f"{directory}/{list_name}.csv"
        if os.path.isfile(fn):
            overrides = pd.read_csv(fn, index_col=0, na_values="n/a")
            attrs[component] = overrides.combine_first(attrs[component])

    return attrs


def get_country(target, **keys):
    """
    Function to convert country codes using pycountry
    Parameters
    ----------
    target: str
        Desired type of country code.
        Examples:
            - 'alpha_3' for 3-digit
            - 'alpha_2' for 2-digit
            - 'name' for full country name
    keys: dict
        Specification of the country name and reference system.
        Examples:
            - alpha_3="ZAF" for 3-digit
            - alpha_2="ZA" for 2-digit
            - name="South Africa" for full country name
    Returns
    -------
    country code as requested in keys or np.nan, when country code is not recognized
    Example of usage
    -------
    - Convert 2-digit code to 3-digit codes: get_country('alpha_3', alpha_2="ZA")
    - Convert 3-digit code to 2-digit codes: get_country('alpha_2', alpha_3="ZAF")
    - Convert 2-digit code to full name: get_country('name', alpha_2="ZA")
    """
    import pycountry as pyc

    assert len(keys) == 1
    try:
        return getattr(pyc.countries.get(**keys), target)
    except (KeyError, AttributeError):
        return np.nan


def two_2_three_digits_country(two_code_country):
    """
    Convert 2-digit to 3-digit country code:
    Parameters
    ----------
    two_code_country: str
        2-digit country name
    Returns
    ----------
    three_code_country: str
        3-digit country name
    """
    if two_code_country == "SN-GM":
        return f"{two_2_three_digits_country('SN')}-{two_2_three_digits_country('GM')}"

    three_code_country = get_country("alpha_3", alpha_2=two_code_country)
    return three_code_country


def three_2_two_digits_country(three_code_country):
    """
    Convert 3-digit to 2-digit country code:
    Parameters
    ----------
    three_code_country: str
        3-digit country name
    Returns
    ----------
    two_code_country: str
        2-digit country name
    """
    if three_code_country == "SEN-GMB":
        return f"{three_2_two_digits_country('SN')}-{three_2_two_digits_country('GM')}"

    two_code_country = get_country("alpha_2", alpha_3=three_code_country)
    return two_code_country


def two_digits_2_name_country(two_code_country):
    """
    Convert 2-digit country code to full name country:
    Parameters
    ----------
    two_code_country: str
        2-digit country name
    Returns
    ----------
    full_name: str
        full country name
    """
    if two_code_country == "SN-GM":
        return f"{two_digits_2_name_country('SN')}-{two_digits_2_name_country('GM')}"

    full_name = get_country("name", alpha_2=two_code_country)
    return full_name


def download_GADM(country_code, update=False, out_logging=False):
    """
    Download gpkg file from GADM for a given country code

    Parameters
    ----------
    country_code : str
        Two letter country codes of the downloaded files
    update : bool
        Update = true, forces re-download of files

    Returns
    -------
    gpkg file per country

    """

    GADM_filename = f"gadm36_{two_2_three_digits_country(country_code)}"
    GADM_url = f"https://biogeo.ucdavis.edu/data/gadm3.6/gpkg/{GADM_filename}_gpkg.zip"
    _logger = logging.getLogger(__name__)
    GADM_inputfile_zip = os.path.join(
        os.getcwd(),
        "data",
        "raw",
        "gadm",
        GADM_filename,
        GADM_filename + ".zip",
    )  # Input filepath zip

    GADM_inputfile_gpkg = os.path.join(
        os.getcwd(),
        "data",
        "raw",
        "gadm",
        GADM_filename,
        GADM_filename + ".gpkg",
    )  # Input filepath gpkg

    if not os.path.exists(GADM_inputfile_gpkg) or update is True:
        if out_logging:
            _logger.warning(
                f"Stage 4/4: {GADM_filename} of country {two_digits_2_name_country(country_code)} does not exist, downloading to {GADM_inputfile_zip}"
            )
        #  create data/osm directory
        os.makedirs(os.path.dirname(GADM_inputfile_zip), exist_ok=True)

        with requests.get(GADM_url, stream=True) as r:
            with open(GADM_inputfile_zip, "wb") as f:
                shutil.copyfileobj(r.raw, f)

        with zipfile.ZipFile(GADM_inputfile_zip, "r") as zip_ref:
            zip_ref.extractall(os.path.dirname(GADM_inputfile_zip))

    return GADM_inputfile_gpkg, GADM_filename


def get_GADM_layer(country_list, layer_id, update=False, outlogging=False):
    """
    Function to retrive a specific layer id of a geopackage for a selection of countries

    Parameters
    ----------
    country_list : str
        List of the countries
    layer_id : int
        Layer to consider in the format GID_{layer_id}.
        When the requested layer_id is greater than the last available layer, then the last layer is selected.
        When a negative value is requested, then, the last layer is requested

    """
    # initialization of the list of geodataframes
    geodf_list = []

    for country_code in country_list:
        # download file gpkg
        file_gpkg, name_file = download_GADM(country_code, update, outlogging)

        # get layers of a geopackage
        list_layers = fiona.listlayers(file_gpkg)

        # get layer name
        if layer_id < 0 | layer_id >= len(list_layers):
            # when layer id is negative or larger than the number of layers, select the last layer
            layer_id = len(list_layers) - 1
        code_layer = np.mod(layer_id, len(list_layers))
        layer_name = (
            f"gadm36_{two_2_three_digits_country(country_code).upper()}_{code_layer}"
        )

        # read gpkg file
        geodf_temp = gpd.read_file(file_gpkg, layer=layer_name)

        # convert country name representation of the main country (GID_0 column)
        geodf_temp["GID_0"] = [
            three_2_two_digits_country(twoD_c) for twoD_c in geodf_temp["GID_0"]
        ]

        # create a subindex column that is useful
        # in the GADM processing of sub-national zones
        geodf_temp["GADM_ID"] = geodf_temp[f"GID_{code_layer}"]

        # concatenate geodataframes
        geodf_list = pd.concat([geodf_list, geodf_temp])

    geodf_GADM = gpd.GeoDataFrame(pd.concat(geodf_list, ignore_index=True))
    geodf_GADM.set_crs(geodf_list[0].crs, inplace=True)

    return geodf_GADM


def locate_bus(
    coords,
    co,
    gadm_level,
    path_to_gadm=None,
    gadm_clustering=False,
    col="name",
):
    """
    Function to locate the right node for a coordinate set
    input coords of point
    Parameters
    ----------
    coords: pandas dataseries
        dataseries with 2 rows x & y representing the longitude and latitude
    co: string (code for country where coords are MA Morocco)
        code of the countries where the coordinates are
    """
    col = "name"
    if not gadm_clustering:
        gdf = gpd.read_file(path_to_gadm)
    else:
        if path_to_gadm:
            gdf = gpd.read_file(path_to_gadm)
            if "GADM_ID" in gdf.columns:
                col = "GADM_ID"

                if gdf[col][0][
                    :3
                ].isalpha():  # TODO clean later by changing all codes to 2 letters
                    gdf[col] = gdf[col].apply(
                        lambda name: three_2_two_digits_country(name[:3]) + name[3:]
                    )
        else:
            gdf = get_GADM_layer(co, gadm_level)
            col = "GID_{}".format(gadm_level)

        # gdf.set_index("GADM_ID", inplace=True)
    gdf_co = gdf[
        gdf[col].str.contains(co)
    ]  # geodataframe of entire continent - output of prev function {} are placeholders
    # in strings - conditional formatting
    # insert any variable into that place using .format - extract string and filter for those containing co (MA)
    point = Point(coords["x"], coords["y"])  # point object

    try:
        return gdf_co[gdf_co.contains(point)][
            col
        ].item()  # filter gdf_co which contains point and returns the bus

    except ValueError:
        return gdf_co[gdf_co.geometry == min(gdf_co.geometry, key=(point.distance))][
            col
        ].item()  # looks for closest one shape=node


def get_conv_factors(sector):
    # Create a dictionary with all the conversion factors from ktons or m3 to TWh based on https://unstats.un.org/unsd/energy/balance/2014/05.pdf
    if sector == "industry":
        fuels_conv_toTWh = {
            "Gas Oil/ Diesel Oil": 0.01194,
            "Motor Gasoline": 0.01230,
            "Kerosene-type Jet Fuel": 0.01225,
            "Aviation gasoline": 0.01230,
            "Biodiesel": 0.01022,
            "Natural gas liquids": 0.01228,
            "Biogasoline": 0.007444,
            "Bitumen": 0.01117,
            "Fuel oil": 0.01122,
            "Liquefied petroleum gas (LPG)": 0.01313,
            "Liquified Petroleum Gas (LPG)": 0.01313,
            "Lubricants": 0.01117,
            "Naphtha": 0.01236,
            "Fuelwood": 0.00254,
            "Charcoal": 0.00819,
            "Patent fuel": 0.00575,
            "Brown coal briquettes": 0.00575,
            "Hard coal": 0.007167,
            "Hrad coal": 0.007167,
            "Other bituminous coal": 0.005556,
            "Anthracite": 0.005,
            "Peat": 0.00271,
            "Peat products": 0.00271,
            "Lignite": 0.003889,
            "Brown coal": 0.003889,
            "Sub-bituminous coal": 0.005555,
            "Coke-oven coke": 0.0078334,
            "Coke oven coke": 0.0078334,
            "Coke Oven Coke": 0.0078334,
            "Gasoline-type jet fuel": 0.01230,
            "Conventional crude oil": 0.01175,
            "Brown Coal Briquettes": 0.00575,
            "Refinery Gas": 0.01375,
            "Petroleum coke": 0.009028,
            "Coking coal": 0.007833,
            "Peat Products": 0.00271,
            "Petroleum Coke": 0.009028,
            "Additives and Oxygenates": 0.008333,
            "Bagasse": 0.002144,
            "Bio jet kerosene": 0.011111,
            "Crude petroleum": 0.011750,
            "Gas coke": 0.007326,
            "Gas Coke": 0.007326,
            "Refinery gas": 0.01375,
            "Coal Tar": 0.007778,
            "Paraffin waxes": 0.01117,
            "Ethane": 0.01289,
            "Oil shale": 0.00247,
            "Other kerosene": 0.01216,
        }
    return fuels_conv_toTWh


def aggregate_fuels(sector):
    gas_fuels = [
        "Natural gas (including LNG)",  #
        "Natural Gas (including LNG)",  #
    ]

    oil_fuels = [
        "Motor Gasoline",  ##
        "Liquefied petroleum gas (LPG)",  ##
        "Liquified Petroleum Gas (LPG)",  ##
        "Fuel oil",  ##
        "Kerosene-type Jet Fuel",  ##
        "Conventional crude oil",  #
        "Crude petroleum",  ##
        "Lubricants",
        "Naphtha",  ##
        "Gas Oil/ Diesel Oil",  ##
        "Petroleum coke",  ##
        "Petroleum Coke",  ##
        "Ethane",  ##
        "Bitumen",  ##
        "Refinery gas",  ##
        "Additives and Oxygenates",  #
        "Refinery Gas",  ##
        "Aviation gasoline",  ##
        "Gasoline-type jet fuel",  ##
        "Paraffin waxes",  ##
        "Natural gas liquids",  #
        "Other kerosene",
    ]

    biomass_fuels = [
        "Bagasse",  #
        "Fuelwood",  #
        "Biogases",
        "Biogasoline",  #
        "Biodiesel",  #
        "Charcoal",  #
        "Black Liquor",  #
        "Bio jet kerosene",  #
        "Animal waste",  #
        "Industrial Waste",  #
        "Industrial waste",
        "Municipal Wastes",  #
        "Vegetal waste",
    ]

    coal_fuels = [
        "Anthracite",
        "Brown coal",  #
        "Brown coal briquettes",  #
        "Coke oven coke",
        "Coke-oven coke",
        "Coke Oven Coke",
        "Coking coal",
        "Hard coal",  #
        "Hrad coal",  #
        "Other bituminous coal",
        "Sub-bituminous coal",
        "Coking coal",
        "Coke Oven Gas",  ##
        "Gas Coke",
        "Gasworks Gas",  ##
        "Lignite",  #
        "Peat",  #
        "Peat products",
        "Coal Tar",  ##
        "Brown Coal Briquettes",  ##
        "Gas coke",
        "Peat Products",
        "Oil shale",  #
        "Oil Shale",  #
        "Coal coke",  ##
        "Patent fuel",  ##
        "Blast Furnace Gas",  ##
        "Recovered gases",  ##
    ]

    electricity = ["Electricity"]

    heat = ["Heat", "Direct use of geothermal heat", "Direct use of solar thermal heat"]

    return gas_fuels, oil_fuels, biomass_fuels, coal_fuels, heat, electricity


def progress_retrieve(url, file):
    import urllib

    from progressbar import ProgressBar

    pbar = ProgressBar(0, 100)

    def dlProgress(count, blockSize, totalSize):
        pbar.update(int(count * blockSize * 100 / totalSize))

    urllib.request.urlretrieve(url, file, reporthook=dlProgress)


def get_last_commit_message(path):
    """
    Function to get the last PyPSA-Earth Git commit message
    Returns
    -------
    result : string
    """
    _logger = logging.getLogger(__name__)
    last_commit_message = None
    backup_cwd = os.getcwd()
    try:
        os.chdir(path)
        last_commit_message = (
            subprocess.check_output(
                ["git", "log", "-n", "1", "--pretty=format:%H %s"],
                stderr=subprocess.STDOUT,
            )
            .decode()
            .strip()
        )
    except subprocess.CalledProcessError as e:
        _logger.warning(f"Error executing Git: {e}")

    os.chdir(backup_cwd)
    return last_commit_message


def read_csv_nafix(file, **kwargs):
    "Function to open a csv as pandas file and standardize the na value"
    if "keep_default_na" not in kwargs:
        kwargs["keep_default_na"] = False
    if "na_values" not in kwargs:
        kwargs["na_values"] = NA_VALUES

    if os.stat(file).st_size > 0:
        return pd.read_csv(file, **kwargs)
    else:
        return pd.DataFrame()


def to_csv_nafix(df, path, **kwargs):
    "Function to export a pandas object into a csv and standardize the na value"
    if "na_rep" in kwargs:
        del kwargs["na_rep"]
    # if len(df) > 0:
    if not df.empty or not df.columns.empty:
        return df.to_csv(path, **kwargs, na_rep=NA_VALUES[0])
    else:
        with open(path, "w") as fp:
            pass


def safe_divide(numerator, denominator, default_value=np.nan):
    """
    Safe division function that returns NaN when the denominator is zero
    """
    if denominator != 0.0:
        return numerator / denominator
    else:
        logging.warning(
            f"Division by zero: {numerator} / {denominator}, returning NaN."
        )
        return np.nan


def calculate_annual_investment(name, r, fn):
    """Calculate the annual investment for an installation given a selected WACC.

    Annual investment for the selected installation 'name' is calculated
    using the given WACC as 'discountrate' and properties for the investment
    read from file (CAPEX, FOM in %, lifetime n in years).

    Parameters:
    -----------
    name : str
        of the installation investment, e.g. "onwind".
        Requires corresponding entry in file 'fn'.
    r : float
        discount rate or WACC used to calculate the annuity of the investment.
        In %.
    fn : str or pathlib.Path
        Filename or path to a pandas-readable csv containing the cost and investment
        specific information (investment, FOM, lifetime) for the installation.

    """

    import logging
    from pathlib import Path

    import pandas as pd

    fn = Path(fn)
    assert fn.exists()

    costs = pd.read_csv(fn, comment="#")

    costs = costs[costs["technology"] == name]

    if costs.empty is True:
        logging.info(f"No cost assumptions found for {name}.")
        return 0

    costs = costs.set_index("parameter")

    return calculate_annuity(
        costs.loc["investment", "value"],
        costs.loc["FOM", "value"],
        costs.loc["lifetime", "value"],
        r,
    )


def calculate_annuity(invest, fom, lifetime, r):
    """
    Calculate annuity based on EAC.

    invest - investment
    fom    - annual FOM in percentage of investment
    lifetime - lifetime of investment in years
    r      - discount rate in percent
    """

    r = r / 100.0
    annuity_factor = r / (1.0 - 1.0 / (r + 1.0) ** (lifetime))
    return (annuity_factor + fom / 100.0) * invest


def configure_logging(snakemake, skip_handlers=False):
    """
    Configure the basic behaviour for the logging module.

    Note: Must only be called once from the __main__ section of a script.

    The setup includes printing log messages to STDERR and to a log file defined
    by either (in priority order): snakemake.log.python, snakemake.log[0] or "logs/{rulename}.log".
    Additional keywords from logging.basicConfig are accepted via the snakemake configuration
    file under snakemake.config.logging.

    Parameters
    ----------
    snakemake : snakemake object
        Your snakemake object containing a snakemake.config and snakemake.log.
    skip_handlers : True | False (default)
        Do (not) skip the default handlers created for redirecting output to STDERR and file.
    """

    import logging
    from pathlib import Path

    kwargs = snakemake.config.get("logging", dict())
    kwargs.setdefault("level", "INFO")

    if skip_handlers is False:
        fallback_path = Path(__file__).parent.joinpath(
            "..", "logs", f"{snakemake.rule}.log"
        )
        logfile = snakemake.log.get(
            "python", snakemake.log[0] if snakemake.log else fallback_path
        )
        kwargs.update(
            {
                "handlers": [
                    # Prefer the 'python' log, otherwise take the first log for each
                    # Snakemake rule
                    logging.FileHandler(logfile),
                    logging.StreamHandler(),
                ],
                "datefmt": "%Y-%m-%d %H:%M:%S",
                "format": "%(asctime)s %(name)-14s %(levelname)-8s %(message)s",
            }
        )
    logging.basicConfig(**kwargs)


def extract_technology(b):
    """Extract the technology from a bus name 'b' by removing trailing '(exp)' or '(imp)' and other content in same braket.

    Examples
    --------
    > extract_technology("hydrogen (g) storage (exp)")
    'hydrogen (g) storage (exp)'

    > extract_technology("hydrogen (g) storage")
    'hydrogen (g) storage'

    > extract_technology("battery inverter (charging, exp)")
    'battery inverter'

    > extract_technology("battery inverter (charging) (exp)")
    'battery inverter (charging)'

    """
    import re

    return re.sub("\([\w\s,\.]*?(?:exp|imp)\)$", "", b.strip()).strip()


def get_bus_unit(b, n):
    """Get the 'unit' attribute of bus 'b' from PyPSA network 'n."""

    return n.buses.loc[b]["unit"]


def extract_unit(b, n):
    """Extract the unit of a bus 'b' in the PyPSA network 'n' based on its carrier.

    Carrier name must be '<something> [unit]'.

    Examples
    --------
    > extract_unit('hydrogen (g) (exp)', network)
    't'

    > extract_unit('electricity (exp)', network)
    'MWh'
    """

    import re

    return re.match("^.*?\s*\[?(\w*)\]?$", n.buses.loc[b]["carrier"]).group(1)


def read_efficiencies(fp, year):
    """Read all entries from data/efficiencies.csv for the given year.

    Returns all entries where entries for this specific year exist.
    For all other entries returns the default value where the column "year" == "all".

    Parameters
    ----------
    fp : str or Path
        Filepath to the location of the efficiencies.csv file.
    year : int or str
        Scenario year to compare against

    Returns
    -------
    efficiencies : pd.DataFrame
    """
    import pandas as pd

    # Return efficiency dataframe with year-specific values where
    # values are given for the specific year and returns for all
    # other entries the default (year=="all") value from the file
    # (= update + insert)
    df = pd.read_csv(fp).set_index(["process", "from", "to"])

    # all specific entries for the given scenario year
    specific = df.loc[df["year"] == str(year)].drop(columns="year")

    # Select all entries from defaults where no specific entry exists
    default = df.loc[df["year"] == "all"].drop(columns="year")
    default = default[~default.index.isin(specific.index)]

    # Combine into single dataframe
    efficiencies = pd.concat([specific, default]).reset_index()

    return efficiencies



def lossy_bidirectional_links(n, carrier, efficiencies={}):
    """Split bidirectional links into two unidirectional links to include transmission losses."""

    carrier_i = n.links.query("carrier == @carrier").index

    if (
        not any((v != 1.0) or (v >= 0) for v in efficiencies.values())
        or carrier_i.empty
    ):
        return

    efficiency_static = efficiencies.get("efficiency_static", 1)
    efficiency_per_1000km = efficiencies.get("efficiency_per_1000km", 1)
    compression_per_1000km = efficiencies.get("compression_per_1000km", 0)

    logger.info(
        f"Specified losses for {carrier} transmission "
        f"(static: {efficiency_static}, per 1000km: {efficiency_per_1000km}, compression per 1000km: {compression_per_1000km}). "
        "Splitting bidirectional links."
    )

    n.links.loc[carrier_i, "p_min_pu"] = 0
    n.links.loc[carrier_i, "efficiency"] = (
        efficiency_static
        * efficiency_per_1000km ** (n.links.loc[carrier_i, "length"] / 1e3)
    )
    rev_links = (
        n.links.loc[carrier_i].copy().rename({"bus0": "bus1", "bus1": "bus0"}, axis=1)
    )
    rev_links["length_original"] = rev_links["length"]
    rev_links["capital_cost"] = 0
    rev_links["length"] = 0
    rev_links["reversed"] = True
    rev_links.index = rev_links.index.map(lambda x: x + "-reversed")

    n.links = pd.concat([n.links, rev_links], sort=False)
    n.links["reversed"] = n.links["reversed"].fillna(False).infer_objects(copy=False)
    n.links["length_original"] = n.links["length_original"].fillna(n.links.length)

    # do compression losses after concatenation to take electricity consumption at bus0 in either direction
    carrier_i = n.links.query("carrier == @carrier").index
    if compression_per_1000km > 0:
        n.links.loc[carrier_i, "bus2"] = n.links.loc[carrier_i, "bus0"].map(
            n.buses.location
        )  # electricity
        n.links.loc[carrier_i, "efficiency2"] = (
            -compression_per_1000km * n.links.loc[carrier_i, "length_original"] / 1e3
        )