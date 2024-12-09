import pandas as pd
import pypsa
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as colors
import matplotlib as mpl
import geopandas as gpd
import cartopy.crs as ccrs
import os
from matplotlib.legend_handler import HandlerPatch
from matplotlib.patches import Circle, Ellipse
from matplotlib.colors import ListedColormap
import re
import seaborn as sns
from matplotlib import colors, cm
import cartopy

scen_dict = {'BS': 'Conservative', 'AP':'Realistic', 'NZ':'Optimistic'}


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

def custom_cmap():
    # Define custom RGB colors
    custom_colors = [
        (23/255, 156/255, 125/255),
        (0/255, 91/255, 127/255),
        (178/255, 210/255, 53/255),
        (253/255, 185/255, 19/255),
        (0/255, 133/255, 152/255),
        (57/255, 193/255, 205/255),
        (245/255, 130/255, 32/255),
        (181/255, 131/255, 141/255),
        (110/255, 140/255, 180/255),
        (187/255, 0/255, 86/255),
        (190/255, 200/255, 220/255),
        (130/255, 190/255, 160/255),
        (99/255, 142/255, 131/255),
        (124/255, 21/255, 77/255),
        (233/255, 216/255, 166/255),
        (202/255, 103/255, 2/255),
        (255/255, 180/255, 162/255)
    ]

    # Create a custom colormap
    custom_cmap_colors = ListedColormap(custom_colors)
    return custom_cmap_colors


def calc_expansion(n, carrier=None):
    '''''''returns expansion of generation and link components in MW'''''''    
    gens = n.generators.groupby('carrier').sum()
    inv_gens = gens.p_nom_opt - gens.p_nom

    links = n.links.groupby('carrier').sum()
    inv_links = links.p_nom_opt - links.p_nom

    inv = pd.concat([inv_gens, inv_links])

    if carrier != None:
        try:
            inv = inv.loc[carrier]
        except:
            print('carrier not existing')
    return inv


def calc_loads(n):
    '''''''in TWh'''''''
    loads_t = n.loads_t.p
    loads_t = loads_t[loads_t.columns.drop(list(loads_t.filter(regex='emissions')))]
    return loads_t.sum().sum() / 1e6 * n.snapshot_weightings.iloc[0,0]


def calc_generation(n, tech='all'):
    '''''''in TWh'''''''
    gen_t = n.generators_t.p[n.generators.loc[n.generators.bus.str.contains('_AC$')].index].sum()
    gen_agg = pd.DataFrame(data={'bus':gen_t.index,'generation':gen_t.values})
    gen_agg['carrier'] = n.generators.loc[gen_agg.bus, 'carrier'].values
    gen_agg = gen_agg.groupby('carrier').sum(numeric_only=True) / 1e6 * n.snapshot_weightings.iloc[0,0]

    hydro_gen = n.storage_units_t.p.sum().sum() / 1e6 * n.snapshot_weightings.iloc[0,0]
    gen_agg.loc['hydro'] = [hydro_gen]

    link_gen_pps = n.links.filter(regex=('OCGT|biomass EOP|CHP'), axis=0)
    link_gen = -n.links_t.p1[link_gen_pps.index] / 1e6 * n.snapshot_weightings.iloc[0,0]
    link_gen.columns = link_gen_pps.carrier
    link_gen = link_gen.rename({'biomass EOP':'biomass', 'OCGT':'OCGT', 'urban central gas CHP':'gas_CHP', 'urban central gas CHP CC':'gas_CHP','urban central solid biomass CHP':'biomass_CHP','urban central solid biomass CHP CC':'biomass_CHP'}, axis=1)
    link_gen = link_gen.T.groupby(link_gen.T.index).sum().T
    for c in link_gen.columns:
        if c in gen_agg.index:
            gen_agg.loc[c] += link_gen[c].sum()
        else:
            gen_agg.loc[c] = {'generation':link_gen[c].sum()}

    res_idx = ['solar', 'rooftop-solar', 'onwind', 'onwind2', 'offwind', 'offwind2', 'csp', 'hydro', 'ror']
    if tech == 'all':
        return gen_agg
    elif tech == 'res':
        return gen_agg.loc[res_idx]
    else:
        return gen_agg.loc[tech]
    
    
def calc_util(n, tech):
    '''''Calculated capacity factor for generation technology'''''
    tech_index = n.generators.loc[n.generators.carrier == tech].index

    weightings = pd.DataFrame(
        np.outer(n.snapshot_weightings["generators"], [1.0] * len(tech_index)),
        index=n.snapshots,
        columns=tech_index,
    )
    
    gen_tech = (n.generators_t.p.filter(regex='{}$'.format(tech)) * weightings).sum()
    installed_cap = n.generators.p_nom_opt.filter(regex='{}$'.format(tech))
    year_avail = (n.generators_t.p_max_pu.filter(regex='{}$'.format(tech)) * weightings ).sum()
    
    max_gen_solar=(installed_cap * year_avail)
    
    return (gen_tech/max_gen_solar).mean()


def calc_additional_res(n, n_ref, tech):
    '''''''in GW'''''''

    res_index = n.generators.filter(regex='{}$'.format(tech), axis=0).index

    res_cap = n.generators.p_nom_opt[res_index].sum()
    res_cap_ref = n_ref.generators.p_nom_opt[res_index].sum()

    return (res_cap - res_cap_ref) / 1e3


def calc_additional_elec(n, n_ref):
    '''''''in GW'''''''

    elec_cap = n.links.filter(like='Electrolysis', axis=0).p_nom_opt.sum()
    res_cap_ref = n_ref.links.filter(like='Electrolysis', axis=0).p_nom_opt.sum()

    return (elec_cap - res_cap_ref) / 1e3


def calc_elec_cf(n):
    '''''Calculated capacity factor for electrolysis'''''
    elec_cap = n.links.filter(like='Electrolysis', axis=0).p_nom_opt.sum() *8760
    elec_output = n.links_t.p0.filter(like='Electrolysis').sum().sum() * n.snapshot_weightings.iloc[0,0]

    return elec_output / elec_cap

def calculate_spec_prod_costs(n):
    '''Takes a solved sector-coupled PyPSA network and outputs specific productio costs for one kg hydrogen at export nodes'''
    h2_prod_ex = n.links_t['p0'].filter(like='H2 export') #Amounts of H2 produced and provided for export
    h2_prod_ex.columns = h2_prod_ex.columns.str.strip(' export') #Modify column names to match with MP dataframe
    marginal_prices = n.buses_t.marginal_price.loc[:, h2_prod_ex.columns] #Marginal H2 prices at export nodes
    prod_costs = (h2_prod_ex * marginal_prices).sum(axis=0) #Product of production ampunts and prices yields total production costs for each export node
    spec_prod_costs = prod_costs / h2_prod_ex.sum(axis=0) # Division by total nodal production amount yields specific production costs of hydrogen for each export node
    spec_prod_costs = spec_prod_costs * 33.3 / 1000 #Calculate costs per kg assuming 1 kg H2 equals 33.3 KWh
    return spec_prod_costs

def calc_wap_ptx_exp(n, unit='MWh', agg='total'):
    '''Takes a solved sector-coupled PyPSA network and outputs specific productio costs for one kg exported hydrogen'''
    if 'NH3 export load' in n.loads_t['p'].columns:
        conversion_fact=5.1666 # MWh/t_NH3
    elif 'meOH export load' in n.loads_t['p'].columns:
        conversion_fact=5.53611 # MWh/t_MeOH
    elif 'H2 export load' in n.loads_t['p'].columns:
        conversion_fact=33.3 # MWh/t_H2       
    
    d_h2 = -n.links_t['p1'].filter(like='ship loading') #Amounts of H2 produced and provided for export

    def rename_column(col_name):
        stripped_name = col_name.replace(' ship loading (exp)', '')  # Strip specific text
        return f"{stripped_name} berth (exp)"  # Add new suffix
    d_h2.columns = d_h2.columns.map(rename_column) #Modify column names to match with MP dataframe   
    
    weightings = pd.DataFrame(
        np.outer(n.snapshot_weightings["generators"], [1.0] * len(d_h2.T)),
        index=n.snapshots,
        columns=d_h2.columns,
    )
    d_h2 = d_h2 * weightings
    marginal_prices = n.buses_t.marginal_price.loc[:, d_h2.columns] #Marginal H2 prices at export nodes
    prod_costs = (d_h2 * marginal_prices).sum() #Product of production ampunts and prices yields total production costs for each export node
    # spec_prod_costs = prod_costs / d_h2.sum().sum() # Division by total nodal production amount yields specific production costs of hydrogen for each export node
    # spec_prod_costs = spec_prod_costs/ 1000 #Calculate costs per kg as shipping is per tonnes
    # d_h2 = d_h2.sum().sum() * conversion_fact /1e6
    # return spec_prod_costs, d_h2

    if agg == 'total' and unit=='MWh':
        return prod_costs.sum() / d_h2.sum().sum() / conversion_fact  , d_h2.sum().sum()* conversion_fact /1e6
    elif agg == 'total' and unit=='Kg':
        return prod_costs.sum() / d_h2.sum().sum() / 1000  , d_h2.sum().sum()* conversion_fact /1e6
    elif agg == 'per_node' and unit=='MWh':
        return prod_costs / d_h2.sum() / conversion_fact , d_h2.sum()* conversion_fact /1e6
    elif agg == 'per_node' and unit=='Kg':
        return prod_costs / d_h2.sum() / 1000 , d_h2.sum()* conversion_fact /1e6
    elif agg == 'timeseries' and unit=='MWh':
        return prod_costs / d_h2 / conversion_fact , d_h2* conversion_fact /1e6
    elif agg == 'timeseries' and unit=='Kg':
        return prod_costs / d_h2 / 1000 , d_h2* conversion_fact /1e6



def calc_wap_ptx_imp(n, unit='MWh', agg=True):
    '''Takes a solved sector-coupled PyPSA network and outputs specific productio costs for one kg exported hydrogen'''
    if 'NH3 export load' in n.loads_t['p'].columns:
        conversion_fact=5.1666 # MWh/t_NH3
    elif 'meOH export load' in n.loads_t['p'].columns:
        conversion_fact=5.53611 # MWh/t_MeOH
    elif 'H2 export load' in n.loads_t['p'].columns:
        conversion_fact=33.3 # MWh/t_H2    
    
    d_h2 = n.links_t['p0'].filter(like='ship unloading') #Amounts of H2 produced and provided for export
    
    def rename_column(col_name):
        stripped_name = col_name.replace(' ship unloading (imp)', '')  # Strip specific text
        return f"{stripped_name} berth (imp)"  # Add new suffix

    # Rename columns
    d_h2.columns = d_h2.columns.map(rename_column)

    # h2_prod_ex.columns = h2_prod_ex.columns.str.strip(' evaporation (imp)') #Modify column names to match with MP dataframe
    weightings = pd.DataFrame(
        np.outer(n.snapshot_weightings["generators"], [1.0] * len(d_h2.T)),
        index=n.snapshots,
        columns=d_h2.columns,
    )
    d_h2 = d_h2 * weightings
    marginal_prices = n.buses_t.marginal_price.loc[:, d_h2.columns] #Marginal H2 prices at export nodes
    prod_costs = (d_h2 * marginal_prices).sum() #Product of production ampunts and prices yields total production costs for each export node
    # spec_prod_costs = prod_costs / h2_prod_ex.sum().sum() # Division by total nodal production amount yields specific production costs of hydrogen for each export node
    # spec_prod_costs = spec_prod_costs / 1000 #Calculate costs per kg assuming 1 kg H2 equals 33.3 KWh
    # h2_prod_ex = h2_prod_ex.sum().sum() * conversion_fact /1e6
    # return spec_prod_costs, h2_prod_ex

    if agg and unit=='MWh':
        return prod_costs.sum() / d_h2.sum().sum() / conversion_fact , d_h2.sum().sum() * conversion_fact /1e6
    elif agg and unit=='Kg':
        return prod_costs.sum() / d_h2.sum().sum() / 1000  , d_h2.sum().sum() * conversion_fact /1e6 
    elif not agg and unit=='MWh':
        return prod_costs / d_h2.sum() / conversion_fact , d_h2.sum() * conversion_fact /1e6
    elif not agg and unit=='Kg':
        return prod_costs / d_h2.sum() * conversion_fact / 1000 , d_h2.sum() * conversion_fact /1e6
    

def calc_wap_ptx_evap(n, unit='MWh', agg=True):
    '''Takes a solved sector-coupled PyPSA network and outputs specific productio costs for one kg exported hydrogen'''
    if 'NH3 export load' in n.loads_t['p'].columns:
        conversion_fact=5.1666 # MWh/t_NH3
    elif 'meOH export load' in n.loads_t['p'].columns:
        conversion_fact=5.53611 # MWh/t_MeOH
    elif 'H2 export load' in n.loads_t['p'].columns:
        conversion_fact=33.3 # MWh/t_H2    
    
    d_h2 = n.links_t['p0'].filter(like='NH3 load links') #Amounts of H2 produced and provided for export
    
    def rename_column(col_name):
        stripped_name = col_name.replace(' NH3 load links', '')  # Strip specific text
        return f"{stripped_name} NH3 (g) (imp)"  # Add new suffix

    # Rename columns
    d_h2.columns = d_h2.columns.map(rename_column)

    # h2_prod_ex.columns = h2_prod_ex.columns.str.strip(' evaporation (imp)') #Modify column names to match with MP dataframe
    weightings = pd.DataFrame(
        np.outer(n.snapshot_weightings["generators"], [1.0] * len(d_h2.T)),
        index=n.snapshots,
        columns=d_h2.columns,
    )
    d_h2 = d_h2 * weightings
    marginal_prices = n.buses_t.marginal_price.loc[:, d_h2.columns] #Marginal H2 prices at export nodes
    prod_costs = (d_h2 * marginal_prices).sum() #Product of production ampunts and prices yields total production costs for each export node
    # spec_prod_costs = prod_costs / h2_prod_ex.sum().sum() # Division by total nodal production amount yields specific production costs of hydrogen for each export node
    # spec_prod_costs = spec_prod_costs / 1000 #Calculate costs per kg assuming 1 kg H2 equals 33.3 KWh
    # h2_prod_ex = h2_prod_ex.sum().sum() * conversion_fact /1e6
    # return spec_prod_costs, h2_prod_ex

    if agg and unit=='MWh':
        return prod_costs.sum() / d_h2.sum().sum()  , d_h2.sum().sum()/1e6
    elif agg and unit=='Kg':
        return prod_costs.sum() / d_h2.sum().sum() * conversion_fact / 1000  , d_h2.sum().sum()/1e6
    elif not agg and unit=='MWh':
        return prod_costs / d_h2.sum() , d_h2.sum()/1e6
    elif not agg and unit=='Kg':
        return prod_costs / d_h2.sum() * conversion_fact / 1000 , d_h2.sum()/1e6


def calc_wap_h2_for_ptx(n, unit='MWh', agg=True):
    if 'NH3 export load' in n.loads_t['p'].columns:
        d_h2 = n.links_t['p3'].filter(like='Haber-Bosch') #Amounts of H2 produced at all nodes
        d_h2.columns = n.links.loc[d_h2.columns, 'bus3']
    elif 'H2 export load' in n.loads_t['p'].columns:
        d_h2 = n.links_t['p0'].filter(like='H2 liquefaction') #Amounts of H2 produced at all nodes
        d_h2.columns = n.links.loc[d_h2.columns, 'bus0']
    elif 'meOH export load' in n.loads_t['p'].columns:
        d_h2 = n.links_t['p1'].filter(like='methanolisation') #Amounts of H2 produced at all nodes
        d_h2.columns = n.links.loc[d_h2.columns, 'bus1']      

    conversion_fact=33.3 # MWh/t_H2

    weightings = pd.DataFrame(
        np.outer(n.snapshot_weightings["generators"], [1.0] * len(d_h2.T)),
        index=n.snapshots,
        columns=d_h2.columns,
    )
    d_h2 = d_h2 * weightings
    # d_h2.columns = n.links.loc[d_h2.columns, 'bus0']
    d_h2 = d_h2.groupby(d_h2.columns, axis=1).sum()


    marginal_prices = n.buses_t.marginal_price.loc[:, d_h2.columns] #Marginal H2 prices at export nodes
    h2_costs = (d_h2 * marginal_prices).sum()

    if agg and unit=='MWh':
        return h2_costs.sum() / d_h2.sum().sum()  , d_h2.sum().sum()/1e6
    elif agg and unit=='Kg':
        return h2_costs.sum() / d_h2.sum().sum() * conversion_fact / 1000  , d_h2.sum().sum()/1e6
    elif not agg and unit=='MWh':
        return h2_costs / d_h2.sum() , d_h2.sum()/1e6
    elif not agg and unit=='Kg':
        return h2_costs / d_h2.sum() * conversion_fact / 1000 , d_h2.sum()/1e6
    

def calc_wap_h2_for_ptx_export_nodes(n, export_nodes, unit='MWh', agg=True):
    if 'NH3 export load' in n.loads_t['p'].columns:
        d_h2 = -n.links_t['p3'].filter(regex=f"({'|'.join(export_nodes)}) Haber-Bosch") #Amounts of H2 produced at all nodes
        d_h2.columns = n.links.loc[d_h2.columns, 'bus3']
    elif 'H2 export load' in n.loads_t['p'].columns:
        d_h2 = -n.links_t['p0'].filter(regex=f"({'|'.join(export_nodes)}) H2 liquefaction") #Amounts of H2 produced at all nodes
        d_h2.columns = n.links.loc[d_h2.columns, 'bus0']
    elif 'meOH export load' in n.loads_t['p'].columns:
        d_h2 = -n.links_t['p1'].filter(regex=f"({'|'.join(export_nodes)}) methanolisation") #Amounts of H2 produced at all nodes
        d_h2.columns = n.links.loc[d_h2.columns, 'bus1'] 

    conversion_fact=33.3 # MWh/t_H2

    weightings = pd.DataFrame(
        np.outer(n.snapshot_weightings["generators"], [1.0] * len(d_h2.T)),
        index=n.snapshots,
        columns=d_h2.columns,
    )
    d_h2 = d_h2 * weightings
    # d_h2.columns = n.links.loc[d_h2.columns, 'bus0']
    d_h2 = d_h2.groupby(d_h2.columns, axis=1).sum()


    marginal_prices = n.buses_t.marginal_price.loc[:, d_h2.columns] #Marginal H2 prices at export nodes
    h2_costs = (d_h2 * marginal_prices).sum()
    
    if agg and unit=='MWh':
        return h2_costs.sum() / d_h2.sum().sum()  , d_h2.sum().sum()/1e6
    elif agg and unit=='Kg':
        return h2_costs.sum() / d_h2.sum().sum() * conversion_fact / 1000  , d_h2.sum().sum()/1e6
    elif not agg and unit=='MWh':
        return h2_costs / d_h2.sum() , d_h2.sum()/1e6
    elif not agg and unit=='Kg':
        return h2_costs / d_h2.sum() * conversion_fact / 1000 , d_h2.sum()/1e6


def calc_wap_ptx_prod(n, unit='MWh', agg=True):
    '''Takes a solved sector-coupled PyPSA network and outputs specific production costs for one kg exported hydrogen'''
    if 'NH3 export load' in n.loads_t['p'].columns:
        d_h2 = -n.links_t['p1'].filter(like='Haber-Bosch') #Amounts of NH3 produced at all nodes
        conversion_fact=5.1666 # MWh/t_NH3
    elif 'meOH export load' in n.loads_t['p'].columns:
        d_h2 = -n.links_t['p1'].filter(like='methanolisation') #Amounts of meOH produced at all nodes
        conversion_fact=5.53611 # MWh/t_MeOH
    elif 'H2 export load' in n.loads_t['p'].columns:
        d_h2 = -n.links_t['p1'].filter(like='Electrolysis') * 0 #Amounts of H2 produced at all nodes
        conversion_fact=33.3 # MWh/t_H2

    weightings = pd.DataFrame(
        np.outer(n.snapshot_weightings["generators"], [1.0] * len(d_h2.T)),
        index=n.snapshots,
        columns=d_h2.columns,
    )
    d_h2 = d_h2 * weightings
    d_h2.columns = n.links.loc[d_h2.columns, 'bus1']
    d_h2 = d_h2.groupby(d_h2.columns, axis=1).sum()


    marginal_prices = n.buses_t.marginal_price.loc[:, d_h2.columns] #Marginal H2 prices at export nodes
    h2_costs = (d_h2 * marginal_prices).sum()

    if agg and unit=='MWh':
        return h2_costs.sum() / d_h2.sum().sum()  , d_h2.sum().sum()/1e6
    elif agg and unit=='Kg':
        return h2_costs.sum() / d_h2.sum().sum() * conversion_fact / 1000  , d_h2.sum().sum()/1e6
    elif not agg and unit=='MWh':
        return h2_costs / d_h2.sum() , d_h2.sum()/1e6
    elif not agg and unit=='Kg':
        return h2_costs / d_h2.sum() * conversion_fact / 1000 , d_h2.sum()/1e6
    

def calc_wap_ptx_prod_export_nodes(n, export_nodes, unit='MWh', agg=True):
    '''Takes a solved sector-coupled PyPSA network and outputs specific production costs for one kg exported hydrogen'''
    if 'NH3 export load' in n.loads_t['p'].columns:
        d_h2 = -n.links_t['p1'].filter(regex=f"({'|'.join(export_nodes)}) Haber-Bosch") #Amounts of NH3 produced at all nodes
        conversion_fact=5.1666 # MWh/t_NH3
    elif 'meOH export load' in n.loads_t['p'].columns:
        d_h2 = -n.links_t['p1'].filter(regex=f"({'|'.join(export_nodes)}) methanolisation") #Amounts of meOH produced at all nodes
        conversion_fact=5.53611 # MWh/t_MeOH
    elif 'H2 export load' in n.loads_t['p'].columns:
        d_h2 = -n.links_t['p1'].filter(regex=f"({'|'.join(export_nodes)})Electrolysis") * 0 #Amounts of H2 produced at all nodes
        conversion_fact=33.3 # MWh/t_H2

    weightings = pd.DataFrame(
        np.outer(n.snapshot_weightings["generators"], [1.0] * len(d_h2.T)),
        index=n.snapshots,
        columns=d_h2.columns,
    )
    d_h2 = d_h2 * weightings
    d_h2.columns = n.links.loc[d_h2.columns, 'bus1']
    d_h2 = d_h2.groupby(d_h2.columns, axis=1).sum()


    marginal_prices = n.buses_t.marginal_price.loc[:, d_h2.columns] #Marginal H2 prices at export nodes
    h2_costs = (d_h2 * marginal_prices).sum()

    if agg and unit=='MWh':
        return h2_costs.sum() / d_h2.sum().sum()  , d_h2.sum().sum()/1e6
    elif agg and unit=='Kg':
        return h2_costs.sum() / d_h2.sum().sum() * conversion_fact / 1000  , d_h2.sum().sum()/1e6
    elif not agg and unit=='MWh':
        return h2_costs / d_h2.sum() , d_h2.sum()/1e6
    elif not agg and unit=='Kg':
        return h2_costs / d_h2.sum() * conversion_fact / 1000 , d_h2.sum()/1e6



def calc_wap_ptx_liquef(n, unit='MWh', agg=True):
    '''Takes a solved sector-coupled PyPSA network and outputs specific production costs for one kg exported hydrogen'''
    if 'NH3 export load' in n.loads_t['p'].columns:
        d_h2 = n.links_t['p0'].filter(like='ship loading (exp)') #Amounts of NH3 liquefied at all nodes
        conversion_fact=5.1666 # MWh/t_NH3
    elif 'meOH export load' in n.loads_t['p'].columns:
        d_h2 = 0 # Not applicable
        conversion_fact=5.53611 # MWh/t_MeOH
    elif 'H2 export load' in n.loads_t['p'].columns:
        d_h2 =-n.links_t['p0'].filter(like='ship loading (exp)') #Amounts of H2 liquefied at all nodes
        conversion_fact=33.3 # MWh/t_H2

    weightings = pd.DataFrame(
        np.outer(n.snapshot_weightings["generators"], [1.0] * len(d_h2.T)),
        index=n.snapshots,
        columns=d_h2.columns,
    )
    d_h2 = d_h2 * weightings
    d_h2.columns = n.links.loc[d_h2.columns, 'bus0']
    d_h2 = d_h2.groupby(d_h2.columns, axis=1).sum()


    marginal_prices = n.buses_t.marginal_price.loc[:, d_h2.columns] #Marginal ptx prices at export nodes
    h2_costs = (d_h2 * marginal_prices).sum()

    if agg and unit=='MWh':
        return h2_costs.sum() / d_h2.sum().sum()  , d_h2.sum().sum()/1e6
    elif agg and unit=='Kg':
        return h2_costs.sum() / d_h2.sum().sum() * conversion_fact / 1000  , d_h2.sum().sum()/1e6
    elif not agg and unit=='MWh':
        return h2_costs / d_h2.sum() , d_h2.sum()/1e6
    elif not agg and unit=='Kg':
        return h2_costs / d_h2.sum() * conversion_fact / 1000 , d_h2.sum()/1e6
    

def calc_wap_ptx_liquef_export_ports(n, export_nodes, unit='MWh', agg=True):
    '''Takes a solved sector-coupled PyPSA network and outputs specific production costs for one kg exported hydrogen'''
    if 'NH3 export load' in n.loads_t['p'].columns:
        d_h2 = -n.links_t['p0'].filter(regex=f"({'|'.join(export_nodes)}) ship loading") #Amounts of NH3 liquefied at all nodes
        conversion_fact=5.1666 # MWh/t_NH3
    elif 'meOH export load' in n.loads_t['p'].columns:
        d_h2 = 0 # Not applicable
        conversion_fact=5.53611 # MWh/t_MeOH
    elif 'H2 export load' in n.loads_t['p'].columns:
        d_h2 = -n.links_t['p0'].filter(regex=f"({'|'.join(export_nodes)}) ship loading") #Amounts of H2 liquefied at all nodes
        conversion_fact=33.3 # MWh/t_H2

    weightings = pd.DataFrame(
        np.outer(n.snapshot_weightings["generators"], [1.0] * len(d_h2.T)),
        index=n.snapshots,
        columns=d_h2.columns,
    )
    d_h2 = d_h2 * weightings
    d_h2.columns = n.links.loc[d_h2.columns, 'bus0']
    d_h2 = d_h2.groupby(d_h2.columns, axis=1).sum()


    marginal_prices = n.buses_t.marginal_price.loc[:, d_h2.columns] #Marginal ptx prices at export nodes
    h2_costs = (d_h2 * marginal_prices).sum()

    if agg and unit=='MWh':
        return h2_costs.sum() / d_h2.sum().sum()  , d_h2.sum().sum()/1e6
    elif agg and unit=='Kg':
        return h2_costs.sum() / d_h2.sum().sum() * conversion_fact / 1000  , d_h2.sum().sum()/1e6
    elif not agg and unit=='MWh':
        return h2_costs / d_h2.sum() , d_h2.sum()/1e6
    elif not agg and unit=='Kg':
        return h2_costs / d_h2.sum() * conversion_fact / 1000 , d_h2.sum()/1e6


def calc_wap_h2(n, agg=True):
    '''Takes a solved sector-coupled PyPSA network and outputs specific production costs for one kg exported hydrogen'''
    if 'H2 export load' in n.loads_t['p'].columns:
        d_h2_1 = n.loads_t['p'].filter(like='H2').drop('H2 export load', axis=1) #Amounts of H2 demanded at all nodes
    else:
        d_h2_1 = n.loads_t['p'].filter(like='H2')
    d_h2_2 = n.loads_t['p'].filter(like='fuel cell') #Amounts of H2 demanded for fuel cells

    d_h2 = pd.concat([d_h2_1, d_h2_2])

    weightings = pd.DataFrame(
        np.outer(n.snapshot_weightings["generators"], [1.0] * len(d_h2.T)),
        index=n.snapshots,
        columns=d_h2.columns,
    )
    d_h2 = d_h2 * weightings
    d_h2.columns = n.loads.loc[d_h2.columns, 'bus']
    d_h2 = d_h2.groupby(d_h2.columns, axis=1).sum()

    marginal_prices = n.buses_t.marginal_price.loc[:, d_h2.columns] #Marginal H2 prices at export nodes
    h2_costs = (d_h2 * marginal_prices).sum()
    
    if agg:
        return h2_costs.sum() / d_h2.sum().sum() * 33.3 / 1000
    else:
        return h2_costs / d_h2.sum() * 33.3 / 1000

def calc_curtailment(n):
    '''''Returns curtailment in TWh'''''
    gen_ts = n.generators_t
    max_gen = gen_ts.p_max_pu * 3
    gen = gen_ts.p[max_gen.columns] * 3
    p_nom_max = n.generators.loc[max_gen.columns].p_nom_opt

    curtailment = ((p_nom_max * max_gen) - gen)
    agg_curtailment =  curtailment.sum().sum() / 1e6

    return agg_curtailment / (gen.sum().sum() / 1e6) * 100

def h2_mp(n):
    h2_ind = n.buses[(n.buses.carrier=='H2') & (n.buses.index != 'H2 export bus')].index
    h2_mp = n[h2_ind].buses_t.marginal_price
    return h2_mp.mean().mean()* 33.3 / 1000

def ac_mp(n):
    ac_ind = n.buses[(n.buses.carrier=='AC')].index
    ac_mp = n[ac_ind].buses_t.marginal_price
    return ac_mp.mean().mean()

def calc_sys_h2_price(n):

    h2_ind = n.buses[(n.buses.carrier=='H2') & (n.buses.index != 'H2 export bus')].index

    h2_mp = n[h2_ind].buses_t.marginal_price
    h2_mp.columns = h2_mp.columns.str.strip(" H2")

    h2_ind_industry = n.loads.filter(like='H2 for industry', axis=0).index
    h2_ind_shipping = n.loads.filter(like='H2 for shipping', axis=0).index
    h2_ind_fuelcell = n.loads.filter(like='fuel cell', axis=0).index

    h2_load_industry = n.loads_t.p.loc[:,h2_ind_industry]
    h2_load_industry.columns = h2_load_industry.columns.str.strip(' H2 for industry') #Modify column names to match with MP dataframe

    h2_load_shipping = n.loads_t.p.loc[:,h2_ind_shipping]
    h2_load_shipping.columns = h2_load_shipping.columns.str.strip(' H2 for shipping') #Modify column names to match with MP dataframe

    h2_load_fuelcell = n.loads_t.p.loc[:,h2_ind_fuelcell]
    h2_load_fuelcell.columns = h2_load_fuelcell.columns.str.strip(' land transport fuel cell') #Modify column names to match with MP dataframe

    # h2_prod_ex.columns = h2_prod_ex.columns.str.strip(' export') #Modify column names to match with MP dataframe

    h2_total_load = h2_load_industry + h2_load_shipping + h2_load_fuelcell

    return ((h2_mp * h2_total_load).sum().sum() / h2_total_load.sum().sum())* 33.3 / 1000

    
def c(n):

    h2_ind = n.buses[(n.buses.carrier=='H2') & (n.buses.index != 'H2 export bus')].index

    h2_mp = n[h2_ind].buses_t.marginal_price
    h2_mp.columns = h2_mp.columns.str.strip(" H2")

    h2_ind_industry = n.loads.filter(like='H2 for industry', axis=0).index
    h2_ind_shipping = n.loads.filter(like='H2 for shipping', axis=0).index
    h2_ind_fuelcell = n.loads.filter(like='fuel cell', axis=0).index

    h2_load_industry = n.loads_t.p.loc[:,h2_ind_industry]
    h2_load_industry.columns = h2_load_industry.columns.str.strip(' H2 for industry') #Modify column names to match with MP dataframe

    h2_load_shipping = n.loads_t.p.loc[:,h2_ind_shipping]
    h2_load_shipping.columns = h2_load_shipping.columns.str.strip(' H2 for shipping') #Modify column names to match with MP dataframe

    h2_load_fuelcell = n.loads_t.p.loc[:,h2_ind_fuelcell]
    h2_load_fuelcell.columns = h2_load_fuelcell.columns.str.strip(' land transport fuel cell') #Modify column names to match with MP dataframe

    # h2_prod_ex.columns = h2_prod_ex.columns.str.strip(' export') #Modify column names to match with MP dataframe

    h2_total_load = h2_load_industry + h2_load_shipping + h2_load_fuelcell

    return ((h2_mp * h2_total_load).sum(axis=1) / h2_total_load.sum(axis=1))* 33.3 / 1000

def plot_expansion(network, run_name, key):
    n = network.copy()
    color_dict = {
        'CCGT':'#ee8340',
        'biomass':"green",
        'coal':'k',
        'oil':'#B5A642',
        'onwind':"dodgerblue",
        'offwind':'#6895dd',
        'solar':"orange",
        'rooftop-solar':'#ffef60',
        'OCGT':'wheat',
        'hydro':'b',
        'nuclear':'r',
        'gas':'brown',
        'residential rural solar thermal':'coral',
        'services rural solar thermal':'coral',
        'residential urban decentral solar thermal':'coral',
        'services urban decentral solar thermal':'coral',
        'urban central solar thermal':'coral',
        'csp':'coral',
        'geothermal': '#ba91b1',
        'lignite':"#9e5a01",
        }

    gens = n.generators
    gens.loc[gens.carrier.str.contains('solar thermal'), 'carrier'] = 'csp'
    gens.loc[gens.carrier.str.contains('solar thermal'), 'carrier'] = 'csp'
    gens.loc[gens.carrier.str.contains('offwind'), 'carrier'] = 'offwind'
    gens.loc[gens.carrier.str.contains('onwind'), 'carrier'] = 'onwind'
    gen_grouped = gens.groupby('carrier', as_index=False).sum(numeric_only =True)

    OCGT_exp = n.links.filter(like='OCGT', axis=0).sum().p_nom_opt
    gen_grouped.loc[gen_grouped.carrier == 'OCGT', 'p_nom_opt'] = gen_grouped.loc[gen_grouped.carrier == 'OCGT', 'p_nom'] + OCGT_exp


    stors = n.storage_units
    stors_grouped = stors.groupby('carrier', as_index=False).sum(numeric_only =True)

    techs = pd.concat([gen_grouped.set_index('carrier')[['p_nom', 'p_nom_opt']].divide(1e3), stors_grouped.set_index('carrier')[['p_nom', 'p_nom_opt']].divide(1e3)])
    techs.loc['hydro'] = techs.loc['hydro'] + techs.loc['ror']
    techs.drop('ror', inplace=True)
    techs['color'] = techs.reset_index().carrier.apply(lambda c: color_dict[c]).values
    techs.sort_index(inplace=True)
    techs.reset_index(inplace=True)

    fig, ax = plt.subplots(1, 1)
    fig.set_size_inches(12, 7)
    # techs.p_nom_opt.plot.bar(ax=ax, color=techs.color, alpha=0.5)
    # techs.plot(kind='scatter', x=techs.index, y=techs.p_nom, ax=ax, color=techs.color)
    techs.set_index('carrier').p_nom_opt.plot(kind='bar', ax=ax, color=techs.color, alpha=0.4, label='Bar: p_nom_opt')
    techs.plot(kind='scatter', x='carrier', y='p_nom', ax=ax, c=techs['color'], s=50, label='Scatter: p_nom', marker='o',)

    # Combine handles (legend objects) from both plots
    handles, labels = ax.get_legend_handles_labels()
    bar_legend = plt.Line2D([0], [0], color='grey', label='Bar: p_nom_opt')
    scatter_legend = plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='grey', markersize=10, label='Scatter: p_nom')

    # Add combined legends
    ax.legend(handles=[bar_legend, scatter_legend], loc='upper right')

    plt.xticks(rotation=90)

    ax.set_xlabel('Generation technology')
    ax.set_ylabel('Capacity in GW')

    dict_scenarios= {'AP':"Realistic", "BS":"Conservative", "NZ":"Optimistic"}
    title_str="{0} | {1} Scenario | {2} TWh | {3}".format(key.split("_")[1], check_scenario(run_name), key.split("_")[4], run_name.split("_")[3])
    fig.suptitle(title_str, fontsize=14) #, fontsize=14, backgroundcolor='lightgray', color='black', weight='bold', style='italic', bbox=dict(facecolor='none', edgecolor='black', boxstyle='round,pad=1'))
    fig.savefig(os.getcwd() + '/pypsa-earth-sec/outputs/{}/plots/expansion_{}.png'.format(run_name, key), dpi=300, bbox_inches='tight')
    plt.close()


# def plot_h2_exports(n, sample_rate='W', aggregated=True):
#     links = n.links
#     links_t = n.links_t

#     exp_h2_links = n.links.loc[links.bus1 == 'H2 export bus']
#     exp_h2_links_ts = links_t.p0[exp_h2_links.index] * n.snapshot_weightings.iloc[0,0] / 1e3
#     exp_h2_links_ts = exp_h2_links_ts.resample(sample_rate).sum()

#     if aggregated:
#         exp_h2_links_ts = exp_h2_links_ts.sum(axis=1)

#     fig, ax = plt.subplots(1, 1)

#     exp_h2_links_ts.plot(ax=ax).legend(bbox_to_anchor=(1.1, 1.1))

#     ax.set_ylabel('Export quantity in GWh for chosen sample rate')
#     ax.set_xlabel('Snapshot')
#     if aggregated == False:
#         print('\n\nHighest H2 delivery from {}'.format(exp_h2_links_ts.sum().sort_values(ascending=False).idxmax()))

def plot_nh3_production_per_node(n, run_name, key, sample_rate='W'):
    # Filter links and prepare the production time series
    links = n.links
    links_t = n.links_t

    exp_h2_links = n.links.loc[links.index.str.contains('Haber-Bosch')].index
    exp_h2_links_prod_ts = links_t.p1[exp_h2_links] * -n.snapshot_weightings.iloc[0, 0] / 1e3

    # Strip 'Haber-Bosch' from column names
    exp_h2_links_prod_ts.columns = exp_h2_links_prod_ts.columns.str.replace('Haber-Bosch', '', regex=False)

    exp_h2_links_prod_ts = exp_h2_links_prod_ts.resample(sample_rate).sum()

    # Prepare colors for bars
    colors = plt.cm.get_cmap('tab20', 35).colors

    # Create a bar plot
    fig, ax = plt.subplots(1, 1,figsize=(12, 8))

    # Summarize the production quantity by week
    exp_h2_links_prod_ts_sum = exp_h2_links_prod_ts.sum(axis=0)


    # Convert series to DataFrame to get x and y values for bars
    data = exp_h2_links_prod_ts_sum.reset_index()
    data.columns = ['Week', 'Production']
    x = data['Week']
    y = data['Production']

    # Create the bar chart
    bars = ax.bar(x, y, color=colors)

    # Calculate the total generation value
    total_generation = round(data['Production'].sum() / 1e3, 0)

    # Add the total generation value as text on the plot
    ax.text(0.8, 0.96, f'Total generation: {total_generation:.0f} TWh',
            transform=ax.transAxes, fontsize=14,
            verticalalignment='top', horizontalalignment='center',
            bbox=dict(facecolor='white', alpha=0.9, edgecolor='black'))


    # Set labels
    ax.set_ylabel('Ammonia production quantity per node [GWh]')
    # ax.set_xlabel('Nodes')

    # Optional: Rotate x labels for better readability if needed
    plt.xticks(rotation=90)

    # Remove vertical grid lines
    ax.yaxis.grid(True)  # Enable horizontal grid lines
    ax.xaxis.grid(False)  # Disable vertical grid lines

    dict_scenarios= {'AP':"Realistic", "BS":"Conservative", "NZ":"Optimistic"}
    title_str="{0} | {1} Scenario | {2} TWh".format(key.split("_")[1], check_scenario(run_name), key.split("_")[4], run_name.split("_")[2])
    plt.title(title_str, fontsize=14) #, fontsize=14, backgroundcolor='lightgray', color='black', weight='bold', style='italic', bbox=dict(facecolor='none', edgecolor='black', boxstyle='round,pad=1'))


    # Show plot
    plt.tight_layout()
    fig.savefig(os.getcwd() + '/pypsa-earth-sec/outputs/{}/plots_scenarios/nh3_prod_per_node_{}.png'.format(run_name, key), dpi=300, bbox_inches='tight')
    plt.close()


def plot_storage_expansion_per_node_(n, run_name, key):
    df = pd.DataFrame(data={
            'Underground H2 storage':calc_uhs_capa(n, agg=False),
            'Aboveground H2 storage':calc_ahs_capa(n, agg=False),
            'Underground CO2 storage':calc_uco2s_capa(n, agg=False),
            'Aboveground CO2 storage':calc_aco2s_capa(n, agg=False),
            'Ammonia storage':calc_anh3s_capa_exp(n, agg=False),
            'Ammonia storage in import land':calc_anh3s_capa_imp(n, agg=False),
            'Methanol storage':calc_ameohs_capa_exp(n, agg=False),
            'Methanol storage in import land':calc_ameohs_capa_imp(n, agg=False),
        })

    df =df.fillna(0)
    # Remove everything after "AC" "MOEH" and "NH3 from the index
    df.index = df.index.to_series().str.replace(r'(AC).*', r'\1', regex=True).str.strip()
    df.index = df.index.to_series().str.replace(r'(NH3).*', r'\1', regex=True).str.strip()
    df.index = df.index.to_series().str.replace(r'(MOEH).*', r'\1', regex=True).str.strip()

    df = df.groupby(df.index).sum()

    df = df.loc[:, (df != 0).any(axis=0)]


    # Prepare colors for bars
    colors = plt.cm.get_cmap('tab20', 35).colors

    # Create a bar plot
    fig, ax = plt.subplots(1, 1,figsize=(12, 8))
    df.plot(ax=ax, kind='bar', stacked=True)

    # Set labels
    ax.set_ylabel('Storage expansion per node [TWh]')
    # ax.set_xlabel('Nodes')

    # Optional: Rotate x labels for better readability if needed
    plt.xticks(rotation=90)

    # Remove vertical grid lines
    ax.yaxis.grid(True)  # Enable horizontal grid lines
    ax.xaxis.grid(False)  # Disable vertical grid lines

    dict_scenarios= {'AP':"Realistic", "BS":"Conservative", "NZ":"Optimistic"}
    title_str="{0} | {1} Scenario | {2} TWh".format(key.split("_")[1], check_scenario(run_name), key.split("_")[4], run_name.split("_")[2])
    plt.title(title_str, fontsize=14) #, fontsize=14, backgroundcolor='lightgray', color='black', weight='bold', style='italic', bbox=dict(facecolor='none', edgecolor='black', boxstyle='round,pad=1'))


    # Show plot
    plt.tight_layout()
    fig.savefig(os.getcwd() + '/pypsa-earth-sec/outputs/{}/plots_scenarios/storage_expansion_per_node_{}.png'.format(run_name, key), dpi=300, bbox_inches='tight')
    plt.close()


def plot_h2_production_per_node(n, run_name, key, sample_rate='W'):
    # Filter links and prepare the production time series
    links = n.links
    links_t = n.links_t

    exp_h2_links = n.links.loc[links.carrier.str.contains('H2 Electrolysis')].index
    exp_h2_links_prod_ts = links_t.p1[exp_h2_links] * -n.snapshot_weightings.iloc[0, 0] / 1e3

    # Strip 'H2 Electrolysis' from column names
    exp_h2_links_prod_ts.columns = exp_h2_links_prod_ts.columns.str.replace('H2 Electrolysis', '', regex=False)

    exp_h2_links_prod_ts = exp_h2_links_prod_ts.resample(sample_rate).sum()

    # Prepare colors for bars
    colors = plt.cm.get_cmap('tab20', 35).colors

    # Create a bar plot
    fig, ax = plt.subplots(1, 1,figsize=(12, 8))

    # Summarize the production quantity by week
    exp_h2_links_prod_ts_sum = exp_h2_links_prod_ts.sum(axis=0)


    # Convert series to DataFrame to get x and y values for bars
    data = exp_h2_links_prod_ts_sum.reset_index()
    data.columns = ['Week', 'Production']
    x = data['Week']
    y = data['Production']

    # Create the bar chart
    bars = ax.bar(x, y, color=colors)

    # Calculate the total generation value
    total_generation = round(data['Production'].sum() / 1e3, 0)

    # Add the total generation value as text on the plot
    ax.text(0.8, 0.96, f'Total generation: {total_generation:.0f} TWh',
            transform=ax.transAxes, fontsize=14,
            verticalalignment='top', horizontalalignment='center',
            bbox=dict(facecolor='white', alpha=0.9, edgecolor='black'))


    # Set labels
    ax.set_ylabel('Hydrogen production quantity per node [GWh]')
    # ax.set_xlabel('Nodes')

    # Optional: Rotate x labels for better readability if needed
    plt.xticks(rotation=90)

    # Remove vertical grid lines
    ax.yaxis.grid(True)  # Enable horizontal grid lines
    ax.xaxis.grid(False)  # Disable vertical grid lines

    dict_scenarios= {'AP':"Realistic", "BS":"Conservative", "NZ":"Optimistic"}
    title_str="{0} | {1} Scenario | {2} TWh".format(key.split("_")[1], check_scenario(run_name), key.split("_")[4], run_name.split("_")[2])
    plt.title(title_str, fontsize=14) #, fontsize=14, backgroundcolor='lightgray', color='black', weight='bold', style='italic', bbox=dict(facecolor='none', edgecolor='black', boxstyle='round,pad=1'))


    # Show plot
    plt.tight_layout()
    fig.savefig(os.getcwd() + '/pypsa-earth-sec/outputs/{}/plots_scenarios/h2_prod_per_node_{}.png'.format(run_name, key), dpi=300, bbox_inches='tight')
    plt.close()


def gas_prod(n, run_name, key):
    gas_prod = n.links[n.links.bus1.str.contains("gas")]
    gas_prod = (gas_prod.groupby('carrier').sum(numeric_only=True) / 1e6 * n.snapshot_weightings.iloc[0,0]).p_nom_opt

   # Create a bar plot
    fig, ax = plt.subplots(1, 1,figsize=(8, 6))
    gas_prod.plot(ax=ax, kind='bar')

    # Set labels
    ax.set_ylabel('Gas production from differnt carriers [MWh]')
    ax.set_xlabel('Carrier')

    # Optional: Rotate x labels for better readability if needed
    plt.xticks(rotation=90)

    # Remove vertical grid lines
    ax.yaxis.grid(True)  # Enable horizontal grid lines
    ax.xaxis.grid(False)  # Disable vertical grid lines

    dict_scenarios= {'AP':"Realistic", "BS":"Conservative", "NZ":"Optimistic"}
    title_str="{0} | {1} Scenario | {2}".format(key.split("_")[1], check_scenario(run_name), run_name.split("_")[-2])
    plt.title(title_str, fontsize=14) #, fontsize=14, backgroundcolor='lightgray', color='black', weight='bold', style='italic', bbox=dict(facecolor='none', edgecolor='black', boxstyle='round,pad=1'))
    fig.savefig(os.getcwd() + '/pypsa-earth-sec/outputs/{}/plots/gas_production.png'.format(run_name), dpi=300, bbox_inches='tight')
    plt.close()

def plot_storage_expansion(df, run_name, key):
    storage = df.set_index(['export_quantity'])
    if 'lnh3' in run_name:
        storage = storage[['uhs_cap', 'ahs_cap', 'anh3s_cap_exp', 'anh3s_cap_imp']]
    elif 'meoh' in run_name:
        storage = storage[['uhs_cap', 'ahs_cap', 'ameohs_cap_exp', 'ameohs_cap_imp']]  
    else:
        storage = storage[['uhs_cap', 'ahs_cap']]  

    column_mapping = {
        'uhs_cap': 'Underground H2 storage',
        'ahs_cap': 'Aboveground H2 storage',
        'uco2s_cap': 'Underground CO2 storage',
        'aco2s_cap': 'Aboveground CO2 storage',
        'anh3s_cap_exp': 'Ammonia storage',
        'anh3s_cap_imp': 'Ammonia storage in import land',
        'ameohs_cap_exp': 'Methanol storage',
        'ameohs_cap_imp': 'Methanol storage in import land'
    }

    # Step 3: Rename the columns using the mapping dictionary
    storage.rename(columns=column_mapping, inplace=True)
   
    storage = storage.drop(storage.index[0])

    # Create a bar plot
    fig, ax = plt.subplots(1, 1,figsize=(8, 6))

    storage.plot(ax=ax, kind='bar', stacked=True)

    # Set labels
    ax.set_ylabel('Storage expansion [TWh]')
    ax.set_xlabel('Different export quantitites [TWh]')

    # Optional: Rotate x labels for better readability if needed
    plt.xticks(rotation=0)

    # Remove vertical grid lines
    ax.yaxis.grid(True)  # Enable horizontal grid lines
    ax.xaxis.grid(False)  # Disable vertical grid lines

    dict_scenarios= {'AP':"Realistic", "BS":"Conservative", "NZ":"Optimistic"}
    title_str="{0} | {1} Scenario | {2}".format(key.split("_")[1], check_scenario(run_name), run_name.split("_")[-2])
    plt.title(title_str, fontsize=14) #, fontsize=14, backgroundcolor='lightgray', color='black', weight='bold', style='italic', bbox=dict(facecolor='none', edgecolor='black', boxstyle='round,pad=1'))
    fig.savefig(os.getcwd() + '/pypsa-earth-sec/outputs/{}/plots/storage_expansion.png'.format(run_name), dpi=300, bbox_inches='tight')
    plt.close()

def plot_co2_storage_expansion(df, run_name, key):
    storage = df.set_index(['export_quantity'])

    storage = storage[[ 'uco2s_cap', 'aco2s_cap']]  

    column_mapping = {
        'uhs_cap': 'Underground H2 storage',
        'ahs_cap': 'Aboveground H2 storage',
        'uco2s_cap': 'Underground CO2 storage',
        'aco2s_cap': 'Aboveground CO2 storage',
        'anh3s_cap_exp': 'Ammonia storage',
        'anh3s_cap_imp': 'Ammonia storage in import land',
        'ameohs_cap_exp': 'Methanol storage',
        'ameohs_cap_imp': 'Methanol storage in import land'
    }

    # Step 3: Rename the columns using the mapping dictionary
    storage.rename(columns=column_mapping, inplace=True)
   
    storage = storage.drop(storage.index[0])

    # Create a bar plot
    fig, ax = plt.subplots(1, 1,figsize=(8, 6))

    storage.plot(ax=ax, kind='bar', stacked=True)

    # Set labels
    ax.set_ylabel('Storage expansion [Mt_Co2]')
    ax.set_xlabel('Different export quantitites [TWh]')

    # Optional: Rotate x labels for better readability if needed
    plt.xticks(rotation=0)

    # Remove vertical grid lines
    ax.yaxis.grid(True)  # Enable horizontal grid lines
    ax.xaxis.grid(False)  # Disable vertical grid lines

    dict_scenarios= {'AP':"Realistic", "BS":"Conservative", "NZ":"Optimistic"}
    title_str="{0} | {1} Scenario | {2}".format(key.split("_")[1], check_scenario(run_name), run_name.split("_")[-2])
    plt.title(title_str, fontsize=14) #, fontsize=14, backgroundcolor='lightgray', color='black', weight='bold', style='italic', bbox=dict(facecolor='none', edgecolor='black', boxstyle='round,pad=1'))
    fig.savefig(os.getcwd() + '/pypsa-earth-sec/outputs/{}/plots/co2_storage_expansion.png'.format(run_name), dpi=300, bbox_inches='tight')
    plt.close()

def plot_ptx_export_costs(df, run_name, key):
    cum_costs = df.set_index(['export_quantity'])
    cum_costs = cum_costs[['h2_for_ptx_cost_mp', 'prod_ptx_cost_mp', 'liqu_ptx_cost_mp', 'exp_ptx_cost_mp','imp_ptx_cost_mp', 'evap_ptx_cost_mp']]
    cum_costs = cum_costs.drop(cum_costs.index[0])

    # Subtract the previous column's value from the current column, except for the first column
    cum_costs.iloc[:, 1:] = cum_costs.iloc[:, 1:].subtract(cum_costs.iloc[:, :-1].values, axis=0)

    # Create a bar plot
    fig, ax = plt.subplots(1, 1,figsize=(8, 6))

    cum_costs.plot(ax=ax, kind='bar', stacked=True)

    # Set labels
    ax.set_ylabel('Cumulative marginal export costs of PtX export [€/MWh]')
    ax.set_xlabel('Different export quantitites [TWh]')

    # Optional: Rotate x labels for better readability if needed
    plt.xticks(rotation=0)

    # Remove vertical grid lines
    ax.yaxis.grid(True)  # Enable horizontal grid lines
    ax.xaxis.grid(False)  # Disable vertical grid lines

    dict_scenarios= {'AP':"Realistic", "BS":"Conservative", "NZ":"Optimistic"}
    title_str="{0} | {1} Scenario | {2}".format(key.split("_")[1], check_scenario(run_name), run_name.split("_")[-2])
    plt.title(title_str, fontsize=14) #, fontsize=14, backgroundcolor='lightgray', color='black', weight='bold', style='italic', bbox=dict(facecolor='none', edgecolor='black', boxstyle='round,pad=1'))
    fig.savefig(os.getcwd() + '/pypsa-earth-sec/outputs/{}/plots/ptx_cumulative_costs.png'.format(run_name), dpi=300, bbox_inches='tight')
    plt.close()

def plot_ptx_export_costs_export_nodes(df, run_name, key):
    cum_costs = df.set_index(['export_quantity'])
    cum_costs = cum_costs[['h2_for_ptx_cost_mp_export_nodes', 'prod_ptx_cost_mp_export_nodes', 'liqu_ptx_cost_mp_export_nodes', 'exp_ptx_cost_mp','imp_ptx_cost_mp', 'evap_ptx_cost_mp']]
    cum_costs = cum_costs.drop(cum_costs.index[0])

    # Subtract the previous column's value from the current column, except for the first column
    cum_costs.iloc[:, 1:] = cum_costs.iloc[:, 1:].subtract(cum_costs.iloc[:, :-1].values, axis=0)

    # Create a bar plot
    fig, ax = plt.subplots(1, 1,figsize=(8, 6))

    cum_costs.plot(ax=ax, kind='bar', stacked=True)

    # Set labels
    ax.set_ylabel('Cumulative marginal export costs of PtX export [€/MWh]')
    ax.set_xlabel('Different export quantitites [TWh]')

    # Optional: Rotate x labels for better readability if needed
    plt.xticks(rotation=0)

    # Remove vertical grid lines
    ax.yaxis.grid(True)  # Enable horizontal grid lines
    ax.xaxis.grid(False)  # Disable vertical grid lines

    dict_scenarios= {'AP':"Realistic", "BS":"Conservative", "NZ":"Optimistic"}
    title_str="{0} | {1} Scenario | {2}".format(key.split("_")[1], check_scenario(run_name), run_name.split("_")[-2])
    plt.title(title_str, fontsize=14) #, fontsize=14, backgroundcolor='lightgray', color='black', weight='bold', style='italic', bbox=dict(facecolor='none', edgecolor='black', boxstyle='round,pad=1'))
    fig.savefig(os.getcwd() + '/pypsa-earth-sec/outputs/{}/plots/ptx_cumulative_costs_export_nodes.png'.format(run_name), dpi=300, bbox_inches='tight')
    plt.close()

def plot_ptx_export_qty(df, run_name, key):
    cum_costs = df.set_index(['export_quantity'])
    cum_costs = cum_costs[['h2_for_ptx_qty', 'ptx_qty_prod', 'ptx_qty_liqu', 'ptx_qty_exp', 'ptx_qty_imp']]
    cum_costs = cum_costs.drop(cum_costs.index[0])

    # Create a bar plot
    fig, ax = plt.subplots(1, 1,figsize=(8, 6))

    cum_costs.plot(ax=ax, kind='bar', stacked=False)

    # Set labels
    ax.set_ylabel('Supply chain generated quantities for PtX export [TWh]')
    ax.set_xlabel('Different export quantitites [TWh]')

    # Optional: Rotate x labels for better readability if needed
    plt.xticks(rotation=0)

    # Remove vertical grid lines
    ax.yaxis.grid(True)  # Enable horizontal grid lines
    ax.xaxis.grid(False)  # Disable vertical grid lines

    dict_scenarios= {'AP':"Realistic", "BS":"Conservative", "NZ":"Optimistic"}
    title_str="{0} | {1} Scenario | {2}".format(key.split("_")[1], check_scenario(run_name), run_name.split("_")[-2])
    plt.title(title_str, fontsize=14) #, fontsize=14, backgroundcolor='lightgray', color='black', weight='bold', style='italic', bbox=dict(facecolor='none', edgecolor='black', boxstyle='round,pad=1'))
    fig.savefig(os.getcwd() + '/pypsa-earth-sec/outputs/{}/plots/ptx_cumulative_qty.png'.format(run_name), dpi=300, bbox_inches='tight')
    plt.close()


def plot_h2_production(n, run_name, sample_rate='W', aggregated=True):
    links = n.links
    links_t = n.links_t

    exp_h2_links = n.links.loc[links.bus1 == 'H2 export bus'].index.str.rstrip('export') + 'Electrolysis'
    exp_h2_links_prod_ts = links_t.p1[exp_h2_links] * -n.snapshot_weightings.iloc[0,0] / 1e3
    exp_h2_links_prod_ts = exp_h2_links_prod_ts.resample(sample_rate).sum()

    fig, ax = plt.subplots(1, 1)

    if aggregated:
        exp_h2_links_prod_ts = exp_h2_links_prod_ts.sum(axis=1)

    exp_h2_links_prod_ts.plot(ax=ax).legend(bbox_to_anchor=(1.1, 1.1))

    ax.set_ylabel('Production quantity in GWh for chosen sample rate')
    ax.set_xlabel('Snapshot')
    if aggregated == False:
        print('\n\nHighest H2 production quantity in {}'.format(exp_h2_links_prod_ts.sum().sort_values(ascending=False).idxmax()))
    fig.savefig(os.getcwd() + '/pypsa-earth-sec/outputs/{}/plots/h2_production.png'.format(run_name), dpi=300, bbox_inches='tight')
    plt.close()

def ship_loading_timeseries_PtX(network, run_name, key):
    n = network.copy()
    ship_loading_ts = calc_wap_ptx_exp(n, unit='MWh', agg='timeseries')[1] * 1e3
    ship_loading_ts = ship_loading_ts.resample('D').sum()

    ship_loading = round(ship_loading_ts.sum().sum() /1e3, 0)

    # Create a bar plot
    fig, ax = plt.subplots(1, 1,figsize=(15, 8))

    ship_loading_ts.plot(ax=ax, kind='line')

    # Set labels
    ax.set_ylabel('Ship loading timeseries of PtX export [GWh]')
    # ax.set_xlabel('Different export quantitites [TWh]')

    # Optional: Rotate x labels for better readability if needed
    plt.xticks(rotation=0)

    # Remove vertical grid lines
    ax.yaxis.grid(True)  # Enable horizontal grid lines
    ax.xaxis.grid(False)  # Disable vertical grid lines

    dict_scenarios= {'AP':"Realistic", "BS":"Conservative", "NZ":"Optimistic"}
    title_str="{0} | {1} Scenario | {2} | Total ship loading {4} TWh".format(key.split("_")[1], check_scenario(run_name), key.split("_")[4], run_name.split("_")[3], ship_loading)
    plt.title(title_str, fontsize=14) #, fontsize=14, backgroundcolor='lightgray', color='black', weight='bold', style='italic', bbox=dict(facecolor='none', edgecolor='black', boxstyle='round,pad=1'))
    fig.savefig(os.getcwd() + '/pypsa-earth-sec/outputs/{}/plots/ship_loading_timeseries_PtX_{}.png'.format(run_name, key), dpi=300, bbox_inches='tight')
    plt.close()


def convoy_loading_timeseries_PtX(network, run_name, key):
    n = network.copy()

    if 'NH3 export load' in n.loads_t['p'].columns:
        conversion_fact=5.1666 # MWh/t_NH3
    elif 'meOH export load' in n.loads_t['p'].columns:
        conversion_fact=5.53611 # MWh/t_MeOH
    elif 'H2 export load' in n.loads_t['p'].columns:
        conversion_fact=33.3 # MWh/t_H2 

    # Your data processing steps
    convoy_loading_links = n.links.loc[n.links.bus0.str.contains('berth \(exp\)')]
    ts_convoy_loading = n.links_t.p0[convoy_loading_links.index]

    weightings = pd.DataFrame(
        np.outer(n.snapshot_weightings["generators"], [1.0] * len(ts_convoy_loading.T)),
        index=n.snapshots,
        columns=ts_convoy_loading.columns,
    )
    ts_convoy_loading = ts_convoy_loading * weightings

    ts_convoy_loading = ts_convoy_loading * conversion_fact /1e3
    ts_convoy_loading = ts_convoy_loading.resample('D').sum()

    # Apply the transformation to all column names
    ts_convoy_loading.columns = ts_convoy_loading.columns.str.replace(r'^.*?convoy', 'convoy', regex=True)

    # Identify relevant columns for TR_63, TR_58, TR_41
    TR_63 = [col for col in ts_convoy_loading.columns if 'TR.63' in col]
    TR_58 = [col for col in ts_convoy_loading.columns if 'TR.58' in col]
    TR_41 = [col for col in ts_convoy_loading.columns if 'TR.41' in col]

    # Define a custom color map with 20 colors
    cmap = ListedColormap(plt.cm.get_cmap('tab20').colors)

    # Create a figure and axis
    fig, axs = plt.subplots(3, 1, figsize=(15, 15))

    # Plot the data on each subplot with custom color map
    ts_convoy_loading[TR_63].plot(ax=axs[0], color=cmap.colors[:len(TR_63)])
    axs[0].set_title('TR.63')

    ts_convoy_loading[TR_58].plot(ax=axs[1], color=cmap.colors[:len(TR_58)])
    axs[1].set_title('TR.58')

    ts_convoy_loading[TR_41].plot(ax=axs[2], color=cmap.colors[:len(TR_41)])
    axs[2].set_title('TR.41')

    # Customize legend to be on the side for each subplot
    for ax in axs:
        ax.legend(loc='center left', bbox_to_anchor=(1, 0.5))

    # Calculate and print convoy loading
    convoy_loading = round(ts_convoy_loading.sum().sum() /1e3, 0)
    print(convoy_loading)

    plt.subplots_adjust(hspace=0.4)  # Adjust hspace to increase/decrease space between subplots


    # Set labels
    fig.text(-0.01, 0.5, 'Convoy loading timeseries of PtX export [GWh]', va='center', rotation='vertical', fontsize=14)
    # fig.text(0.8, 0.9, 'Total convoy loading {} [TWh]'.format(convoy_loading), va='center', rotation='horizontal', fontsize=14, backgroundcolor='lightgray', color='black', weight='bold')

    # Adjust layout to make room for the title
    plt.tight_layout(rect=[0, 0, 1, 0.96])

    dict_scenarios= {'AP':"Realistic", "BS":"Conservative", "NZ":"Optimistic"}
    title_str="{0} | {1} Scenario | {2} TWh | {3} | Total convoy loading {4} TWh".format(key.split("_")[1], check_scenario(run_name), key.split("_")[4], run_name.split("_")[3], convoy_loading)
    fig.suptitle(title_str, fontsize=14) #, fontsize=14, backgroundcolor='lightgray', color='black', weight='bold', style='italic', bbox=dict(facecolor='none', edgecolor='black', boxstyle='round,pad=1'))
    fig.savefig(os.getcwd() + '/pypsa-earth-sec/outputs/{}/plots/convoy_loading_timeseries_PtX_{}.png'.format(run_name, key), dpi=300, bbox_inches='tight')
    plt.close()

def calc_local_h2_share(n):
    links = n.links
    links_t = n.links_t

    exp_h2_links = n.links.loc[links.bus1 == 'H2 export bus']
    exp_h2_links_ts = links_t.p0[exp_h2_links.index] * n.snapshot_weightings.iloc[0,0] / 1e3
    exp_h2_links_exp = exp_h2_links_ts.sum().sum()

    exp_h2_links = n.links.loc[links.bus1 == 'H2 export bus'].index.str.rstrip('export') + 'Electrolysis'
    exp_h2_links_prod_ts = links_t.p1[exp_h2_links] * -n.snapshot_weightings.iloc[0,0] / 1e3
    exp_h2_links_prod = exp_h2_links_prod_ts.sum().sum()

    return  exp_h2_links_exp / exp_h2_links_prod

def plot_h2_mps(n, sample_rate='W', only_export=True, include_export_bus=False):
    links = n.links
    buses_t = n.buses_t

    if only_export:
        exp_h2_links = n.links.loc[links.bus1 == 'H2 export bus'].index.str.rstrip(' export')
        mp_ts = buses_t.marginal_price[exp_h2_links]
    else:
        mp_ts = buses_t.marginal_price.filter(regex='H2$')

    if include_export_bus:
            exp_bus = n.buses.filter(like='H2 export', axis=0).index
            mp_ts = pd.concat([mp_ts, buses_t.marginal_price[exp_bus]], axis=1)
            
    mp_ts = mp_ts.resample(sample_rate).mean()
    fig, ax = plt.subplots(1, 1)

    mp_ts.plot(ax=ax).legend(bbox_to_anchor=(1.1, 1.1))

    ax.set_ylabel('Average MP for H2')
    ax.set_xlabel('Snapshot')
    print('\n\nHighest mean hydrogen price in {}'.format(mp_ts.mean().sort_values(ascending=False).idxmax()))


def plot_elec_mps(n, sample_rate='W', only_export=True):
    links = n.links
    buses_t = n.buses_t

    if only_export:
        exp_h2_links = n.links.loc[links.bus1 == 'H2 export bus'].index.str.rstrip(' H2 export')
        mp_ts = buses_t.marginal_price[exp_h2_links]
    else:
        mp_ts = buses_t.marginal_price.filter(regex='_AC$')
    mp_ts = mp_ts.resample(sample_rate).mean()
    fig, ax = plt.subplots(1, 1)

    mp_ts.plot(ax=ax).legend(bbox_to_anchor=(1.1, 1.1))

    ax.set_ylabel('Average MP for electricity')
    ax.set_xlabel('Snapshot')
    print('\n\nHighest mean electricity price in {}'.format(mp_ts.mean().sort_values(ascending=False).idxmax()))


def get_fossil_emissions(n):
    '''''in t'''''   
    AC_index = n.buses[n.buses.carrier == 'AC'].index

    # vars_conv_gens = get_var(n, "Store", "e").loc[sns[-1], co2_atmosphere]
    conv_gens = list(n.carriers[n.carriers.co2_emissions > 0].index)
    conv_index = n.generators[n.generators.carrier.isin(conv_gens)].index    
    # vars_conv_gens = n.generators_t.p[conv_index]
    convs = n.generators[n.generators.carrier.isin(conv_gens)]
    conv_index = convs[convs['bus'].isin(AC_index)].index

    conv_gen = n.generators_t.p[conv_index].sum().sum() * n.snapshot_weightings.iloc[0, 0] / 1e6
    print('\nFossil generation amounts to {} TWh'.format(conv_gen))

    n.generators.loc[n.generators.carrier.isin(conv_gens), "emissions"] = 0
    n.generators.loc[conv_index, "emissions"] = n.generators.loc[
    conv_index, "carrier"
    ].apply(lambda x: n.carriers.loc[x].co2_emissions)
    n.generators.emissions = n.generators.emissions.fillna(0)

    weightings = pd.DataFrame(
        np.outer(n.snapshot_weightings["generators"], [1.0] * len(conv_index)),
        index=n.snapshots,
        columns=conv_index,
    )

    emission_factors = pd.DataFrame(
        np.outer(
            [1.0] * len(n.snapshot_weightings["generators"]),
            n.generators.loc[conv_index, "emissions"],
        ),
        index=n.snapshots,
        columns=conv_index,
    )

    return n.generators_t.p[conv_index], weightings, emission_factors, conv_index

def calc_curtailment(n):
    gen_ts = n.generators_t
    max_gen = gen_ts.p_max_pu * 3
    gen = gen_ts.p[max_gen.columns] * 3
    p_nom_max = n.generators.loc[max_gen.columns].p_nom_opt

    curtailment = ((p_nom_max * max_gen) - gen)
    agg_curtailment =  curtailment.sum().sum() / 1e6

    return agg_curtailment / (gen.sum().sum() / 1e6) * 100

def calc_batt_capa(n):
    '''in TWh'''
    return n.stores.filter(like='battery', axis=0).e_nom_opt.sum() / 1e6

def calc_batt_charge_capa(n):
    '''in GW'''
    return n.links.filter(regex='battery charge', axis=0).p_nom_opt.sum() / 1e3

def calc_batt_discharge_capa(n):
    '''in GW'''
    return n.links.filter(regex='battery discharge', axis=0).p_nom_opt.sum() / 1e3

def calc_ptx_demand(n):
    if 'NH3 export load' in n.loads_t['p'].columns:
        return n.loads_t.p.filter(like='NH3').multiply(n.snapshot_weightings.iloc[0,0]).divide(1e6).sum().sum()
    elif 'meOH export load' in n.loads_t['p'].columns:
        return n.loads_t.p.filter(like='meOH').multiply(n.snapshot_weightings.iloc[0,0]).divide(1e6).sum().sum()

def calc_h2_demand(n):
    return n.loads_t.p.filter(like='H2').multiply(n.snapshot_weightings.iloc[0,0]).divide(1e6).sum().sum()

def calc_ac_demand(n):
    return n.loads_t.p.filter(regex='_AC$').multiply(n.snapshot_weightings.iloc[0,0]).divide(1e6).sum().sum()

def calc_demand(n):
    loads = n.loads_t.p.filter(regex='_AC').sum().sum() * n.snapshot_weightings.iloc[0,0] / 1e6
    return loads

def calc_line_capa(n):
    return (n.lines.s_nom_opt * n.lines.length).sum()

def calc_elec_capa(n):
    return n.links.filter(like='Electrolysis', axis=0).p_nom_opt.sum() / 1e3

def calc_solar_capa(n):
    return n.generators.loc[n.generators.carrier == 'solar', 'p_nom_opt'].sum() / 1e3

def calc_onwind_capa(n):
    return n.generators.loc[n.generators.carrier.str.contains('onwind'), 'p_nom_opt'].sum() / 1e3

# def calc_uhs_capa(n):
#     '''in TWH'''
#     return n.stores.filter(like='H2 UHS', axis=0).e_nom_opt.sum() / 1e6

# def calc_ahs_capa(n):
#     '''in TWH'''
#     return n.stores.filter(like='H2 Gas Store Tank', axis=0).e_nom_opt.sum() / 1e6

# def calc_uco2s_capa(n):
#     '''in TWH'''
#     return n.stores.filter(like='co2 stored', axis=0).e_nom_opt.sum() / 1e6

# def calc_aco2s_capa(n):
#     '''in TWH'''
#     return n.stores.filter(like='CO2 storage tank', axis=0).e_nom_opt.sum() / 1e6

# def calc_anh3s_capa_exp(n):
#     '''in TWH'''
#     return n.stores.filter(like='NH3 (l) storage tank incl. liquefaction', axis=0).e_nom_opt.sum() / 1e6

# def calc_anh3s_capa_imp(n):
#     '''in TWH'''
#     return n.stores.filter(like='NH3 (l) storage tank incl. liquefaction (imp)', axis=0).e_nom_opt.sum() / 1e6

# def calc_ameohs_capa_exp(n):
#     '''in TWH'''
#     return n.stores.filter(like='General liquid hydrocarbon storage (product) (exp)', axis=0).e_nom_opt.sum() / 1e6

# def calc_ameohs_capa_imp(n):
#     '''in TWH'''
#     return n.stores.filter(like='General liquid hydrocarbon storage (product)', axis=0).e_nom_opt.sum() / 1e6

def calc_uhs_capa(n, agg=True):
    '''in TWH'''
    if agg:
        return n.stores.filter(like='H2 UHS', axis=0).e_nom_opt.sum() / 1e6
    else:
        return n.stores.filter(like='H2 UHS', axis=0).e_nom_opt / 1e6

def calc_ahs_capa(n, agg=True):
    '''in TWH'''
    if agg:
        return n.stores.filter(like='H2 Gas Store Tank', axis=0).e_nom_opt.sum() / 1e6
    else:
        return n.stores.filter(like='H2 Gas Store Tank', axis=0).e_nom_opt / 1e6

def calc_uco2s_capa(n, agg=True):
    '''in TWH'''
    if agg:
        return n.stores.filter(like='co2 stored', axis=0).e_nom_opt.sum() / 1e6
    else:
        return n.stores.filter(like='co2 stored', axis=0).e_nom_opt / 1e6

def calc_aco2s_capa(n, agg=True):
    '''in TWH'''
    if agg:
        return n.stores.filter(like='CO2 storage tank', axis=0).e_nom_opt.sum() / 1e6
    else:
        return n.stores.filter(like='CO2 storage tank', axis=0).e_nom_opt / 1e6

def calc_anh3s_capa_exp(n, agg=True):
    '''in TWH'''
    if agg:
        return n.stores.loc[(n.stores.carrier.str.contains("NH3 store"))].e_nom_opt.sum() / 1e6
    else:
        return n.stores.loc[(n.stores.carrier.str.contains("NH3 store"))].e_nom_opt / 1e6

def calc_anh3s_capa_imp(n, agg=True):
    '''in TWH'''
    if agg:
        return n.stores.filter(like='NH3 (l) storage tank incl. liquefaction (imp)', axis=0).e_nom_opt.sum() / 1e6
    else:
        return n.stores.filter(like='NH3 (l) storage tank incl. liquefaction (imp)', axis=0).e_nom_opt / 1e6

def calc_ameohs_capa_exp(n, agg=True):
    '''in TWH'''
    if agg:
        return n.stores.filter(like='General liquid hydrocarbon storage (product) (exp)', axis=0).e_nom_opt.sum() / 1e6
    else:
        return n.stores.filter(like='General liquid hydrocarbon storage (product) (exp)', axis=0).e_nom_opt / 1e6

def calc_ameohs_capa_imp(n, agg=True):
    '''in TWH'''
    if agg:
        return n.stores.filter(like='General liquid hydrocarbon storage (product)', axis=0).e_nom_opt.sum() / 1e6
    else:
        return n.stores.filter(like='General liquid hydrocarbon storage (product)', axis=0).e_nom_opt / 1e6


def calc_export_shares(n, absolute=True):
    ex_qs = -n.links_t.p1.filter(like='ship loading (exp)').sum() * n.snapshot_weightings.iloc[0, 0]
    # ex_qs.index = ex_qs.index.str.strip('ship loading (exp)')
    if absolute==False:
        ex_qs_rel = ex_qs / ex_qs.sum()
        return ex_qs_rel
    else:
        return ex_qs / 1e6

def calc_export_shares_2(n, absolute=True):
    # ex_qs = n.links_t.p0.filter(like='H2 export').sum() * 3

    links = n.links
    links_t = n.links_t

    exp_h2_links = n.links.loc[links.bus1 == 'H2 export bus']
    ex_qs = links_t.p0[exp_h2_links.index].sum() * 3


    if absolute==False:
        ex_qs_rel = ex_qs / ex_qs.sum()
        return ex_qs_rel
    else:
        return pd.DataFrame(ex_qs / 1e6)





def calc_wap_elec(n, agg=True):
    '''Takes a solved sector-coupled PyPSA network and returns electricity price per MWh for system or single nodes'''
    d_elec = n.loads_t['p'].filter(regex='AC$') #Amounts of electricity consumed

    weightings = pd.DataFrame(
        np.outer(n.snapshot_weightings["generators"], [1.0] * len(d_elec.T)),
        index=n.snapshots,
        columns=d_elec.columns,
    )
    d_elec = d_elec * weightings
    marginal_prices = n.buses_t.marginal_price.loc[:, d_elec.columns] #Marginal elec prices at nodes
    d_costs = (d_elec * marginal_prices).sum() #Product of demand and prices yields average total value of electricity consumed at nodes
    if agg:
        return d_costs.sum() / d_elec.sum().sum()
    else:
        return d_costs / d_elec.sum()

def calc_geothermal_share(n):
    df = n.generators[n.generators.carrier == 'geothermal']
    exp_share = df['p_nom_opt'].sum()  / df['p_nom_max'].sum()
    return exp_share * 100

def calc_elec_mix(n):
    generation = calc_generation(n) 
    mix = generation.loc[generation.generation > 0] # 0
    # mix = mix.sort_values(by='generation', ascending=False)
    mix = mix.sort_index()
    mix = mix/mix.sum()
    return mix.squeeze()

def calc_energy_mix(n):
    gens = n.generators_t.p / 1e6 * 3
    gens.columns = n.generators.loc[gens.columns, 'carrier'].str.strip()#.apply(rename_techs_tyndp)
    gens = gens.T.groupby(gens.columns).sum().T

    gens_hydro = n.storage_units_t.p_dispatch / 1e6 * 3
    gens_hydro.columns = n.storage_units.loc[gens_hydro.columns, 'carrier'].str.strip()#.apply(rename_techs_tyndp)
    gens_hydro = gens_hydro.T.groupby(gens_hydro.columns).sum().T

    gen_stor = n.stores_t.p.filter(regex='biomass|oil|biogas|gas Store') / 1e6 * 3
    gen_stor.columns = n.stores.loc[gen_stor.columns,'carrier'].str.strip()#.apply(rename_techs_tyndp)

    gen_stor = gen_stor.T.groupby(gen_stor.columns).sum().T#.drop('CCS', axis=1)

    gens = pd.concat([gens, gens_hydro, gen_stor.clip(lower=0)]).fillna(0)
    gens = gens.T.groupby(gens.T.index).sum().T
    gens = gens.groupby(gens.index).sum()
    gens = gens.sum()
    
    return gens.squeeze()


# def plot_energy_mix(df1, run_name):
#     df = df1.copy()
#     df = df.reset_index()
#     fig, ax = plt.subplots(1,3)
#     fig.set_size_inches(20, 6)

#     #demand = df.loc[df.scenario == s].set_index(['year', 'scenario', 'export_quantity']).ac_demand
#     for (idx_s,s) in enumerate(df.scenario.unique()):
#         df_s = df.loc[df.scenario == s].set_index(['year', 'scenario', 'export_quantity'])[['energy_mix_abs']]
#         df_s_tech = df_s.energy_mix_abs.apply(lambda m: pd.Series(m.split('\n')[1:]).apply(lambda s: s.split('   ')[0]))
#         df_s_shares = df_s.energy_mix_abs.apply(lambda m: pd.Series(m.split('\n')[1:]).apply(lambda s: float(s.split('   ')[-1])))
#         df_s_shares.columns = df_s_tech.iloc[0].values
#         df_s_shares = df_s_shares[df_s_shares > 0.5].dropna(axis=1)
#         df_s_shares = df_s_shares.T.sort_values(by=(df_s_shares.index.get_level_values(0)[0], s, 0), ascending=False).T

#         # #df_s_key = pd.Series(summary_res.electricity_mix_rel.iloc[0].split('\n')).apply(lambda s: s.split(' ')[0])
#         # df_s_value = pd.Series(summary_res.electricity_mix_rel.iloc[0].split('\n')).apply(lambda s: s.split(' ')[-1])
#         # df_s_value = df_s_value.iloc[1:].astype(float)
#         # df_s_value.index = df_s_key.iloc[1:].values
#         #mix_s = pd.DataFrame(index=df_s.index, data=df_s_value.to_dict())
#         #mix_s = mix_s * demand
#         colors={
#             'solar':'gold',
#             'onwind':'steelblue',
#             'onwind2':'royalblue',
#             'offwind':'lightblue',
#             'offwind2':'cyan',
#             'rooftop-solar':'orange',
#             'csp':'coral',
#             'solar thermal':'lightcoral',
#             'biomass':'green',
#             'solid biomass':'green',
#             'hydro':'midnightblue',
#             'ror':'slateblue',
#             'nuclear':'greenyellow',
#             'coal':'brown',
#             'OCGT':'red',
#             'CCGT':'#ee8340',
#             'oil':'#B5A642',
#             'biogas':'lawngreen',
#             'gas':'crimson',
#             'lignite':'grey',
#             'geothermal': '#ba91b1'
#         }
        
#         df_s_shares.plot.bar(stacked=True, ax=ax[idx_s], color=df_s_shares.columns.map(colors))

#         ax[idx_s].set_ylabel('Energy share [MWh]')
        
#         h, l = ax[idx_s].get_legend_handles_labels()
#         #ax[idx_s].legend(bbox_to_anchor=(0.6,1.3), ncol=3, handles=h[:int(len(h)/3)], labels=l[:int(len(l)/3)])
#         ax[idx_s].legend(bbox_to_anchor=(1,1.3), ncol=3, handles=h, labels=l)
#     fig.savefig(os.getcwd()+'/pypsa-earth-sec/outputs/{}/plots/energy_mix.png'.format(run_name), dpi=300, bbox_inches='tight')


def calc_h2_pipeline_cap(n):
    pipelines = n.links.filter(like='H2 pipeline', axis=0)
    pipeline_capa = pipelines.p_nom_opt * pipelines.length
    return pipeline_capa.sum()

def calc_nh3_pipeline_cap(n):
    pipelines = n.links.filter(like='NH3 pipeline', axis=0)
    pipeline_capa = pipelines.p_nom_opt * pipelines.length
    return pipeline_capa.sum()

def calc_meoh_pipeline_cap(n):
    pipelines = n.links.filter(like='meOH pipeline', axis=0)
    pipeline_capa = pipelines.p_nom_opt * pipelines.length
    return pipeline_capa.sum()

def calc_co2_pipeline_cap(n):
    pipelines = n.links.filter(like='CO2 pipeline', axis=0)
    pipeline_capa = pipelines.p_nom_opt * pipelines.length
    return pipeline_capa.sum()

def calc_emissions(n):
    emissions = n.stores_t.p.filter(like='atmosphere').squeeze().sum() * n.snapshot_weightings['generators'].iloc[0]
    return emissions


def create_summary_df(run_name):
    summary = pd.DataFrame()
    path = os.getcwd()+'/pypsa-earth-sec/results/{}/postnetworks'.format(run_name)
    exp_ports_all = []

    # Define a function to extract both text and number
    def extract_sort_key(filepath):
        match = re.search(r'([A-Z]{2})_(\d+)export', filepath)
        if match:
            text = match.group(1)
            number = int(match.group(2))
            return (text, number)
        return ('', 0)

    # Sort based on both text and number
    file_list = sorted(os.listdir(path), key=extract_sort_key)

    # file_list = sorted(os.listdir(path))
    # file_list = sorted(os.listdir(path), key=lambda x: int(re.search(r'_\d+(?=\D)', x).group(0)[1:]))

    for i, f in enumerate(file_list):
    # for f in os.listdir(path):
        n_path = path+'/{}'.format(f)
        q = int(f.split('_')[-3].split('e')[0])
        scen = f.split('_')[-4]
        year = f.split('_')[-6]
        i_rate = f.split('_')[-5]

        # Define the regex pattern to match the substring between the second-to-last underscore and ".nc"
        pattern = r'export_(\w+)\.nc'
        # Search for the pattern in the text
        match = re.search(pattern, f)
        # Extract the matched group
        if match:
            export_profile = match.group(1)
        else:
            export_profile = None

        n = pypsa.Network(n_path)

        #system costs
        system_costs = n.objective
        system_costs_corr = system_costs + n.objective_constant
        if q == 0:
            system_costs_no_exports= system_costs
            system_costs_no_exports_corr = system_costs_corr

        #average costs of exported hydrogen
        hydrogen_costs = (system_costs - system_costs_no_exports) / (q*1e9) * 33.3
        hydrogen_costs_corr = (system_costs_corr - system_costs_no_exports_corr) / (q*1e9) * 33.3


        #local markt prices
        elec_wap = calc_wap_elec(n)
        h2_wap = calc_wap_h2(n)

        # #supply chain marginal prices
        # h2_wap_for_ptx = calc_wap_h2_for_ptx(n)[0]
        # ptx_wap_prod = calc_wap_ptx_prod(n)[0]
        # ptx_wap_liqu = calc_wap_ptx_liquef(n)[0]
        # ptx_wap_exp = calc_wap_ptx_exp(n)[0]
        # ptx_wap_imp = calc_wap_ptx_imp(n)[0]

        # #supply chain quantities 
        # h2_qty_for_ptx = calc_wap_h2_for_ptx(n)[1]
        # ptx_qty_prod = calc_wap_ptx_prod(n)[1]
        # ptx_qty_liqu = calc_wap_ptx_liquef(n)[1]
        # ptx_qty_exp = calc_wap_ptx_exp(n)[1]
        # ptx_qty_imp = calc_wap_ptx_imp(n)[1]
    
        #energy demand
        demand = calc_demand(n) + q
        ac_demand = calc_ac_demand(n)
        h2_demand = calc_h2_demand(n)
        ptx_demand = calc_ptx_demand(n)


        #curtailment
        curtailment = calc_curtailment(n)
        
        exp_ports = n.links.filter(like='ship loading', axis=0).index#.str.strip('ship loading (exp)')


        #export port shares and export h2 price according to MP
        if '_0export' in f:
            
            #supply chain marginal prices
            h2_wap_for_ptx = calc_wap_h2_for_ptx(n)[0]
            ptx_wap_prod = calc_wap_ptx_prod(n)[0]
            ptx_wap_liqu = calc_wap_ptx_liquef(n)[0]
            ptx_wap_exp = calc_wap_ptx_exp(n)[0]
            ptx_wap_imp = calc_wap_ptx_imp(n)[0]
            ptx_wap_evap = calc_wap_ptx_evap(n)[0]
            

            #supply chain quantities 
            h2_qty_for_ptx = calc_wap_h2_for_ptx(n)[1]
            ptx_qty_exp = calc_wap_ptx_exp(n)[1]
            ptx_qty_prod = calc_wap_ptx_prod(n)[1]
            ptx_qty_liqu = calc_wap_ptx_liquef(n)[1]
            ptx_qty_exp = calc_wap_ptx_exp(n)[1]
            ptx_qty_imp = calc_wap_ptx_imp(n)[1]

            exp_shares = pd.Series(np.zeros(len(exp_ports)), index=exp_ports)
            if i < len(file_list) - 1:
                # Get the export ports of the next file (f+1)
                next_f = file_list[i + 1]
                # if '_0export' in next_f:
                #     next_f = file_list[i + 2]
                #     next_n_path = path + '/{}'.format(next_f)
                #     next_n = pypsa.Network(next_n_path)
                #     exp_ports_all = next_n.links.filter(like='export', axis=0).index
                # else:
                next_n_path = path + '/{}'.format(next_f)
                next_n = pypsa.Network(next_n_path)
                exp_ports_all = next_n.links.filter(like='ship loading (exp)', axis=0).index#.str.strip('ship loading (exp)')
            # if q == 0:
        #     hydrogen_wap_exp = 0
        #     exp_shares = pd.Series(np.zeros(len(exp_ports)), index=exp_ports)
        #     exp_ports_all = exp_ports
        # #     exp_ports_0 = exp_ports
        # # elif q == 1 or q == 10:
        # #     hydrogen_wap_exp = calc_wap_h2_exp(n)
        # #     exp_shares = calc_export_shares(n)
        # #     exp_ports = exp_ports_0

                export_nodes = exp_ports_all.str.strip('ship loading (exp)')
                h2_wap_for_ptx_export_nodes = calc_wap_h2_for_ptx_export_nodes(n, export_nodes)[0]
                ptx_wap_prod_export_nodes = calc_wap_ptx_prod_export_nodes(n, export_nodes)[0]
                ptx_wap_liqu_export_nodes = calc_wap_ptx_liquef_export_ports(n, export_nodes)[0]
        else:
            export_nodes = exp_ports_all.str.strip('ship loading (exp)')

            #supply chain marginal prices at export nodes
            h2_wap_for_ptx_export_nodes = calc_wap_h2_for_ptx_export_nodes(n, export_nodes)[0]
            ptx_wap_prod_export_nodes = calc_wap_ptx_prod_export_nodes(n, export_nodes)[0]
            ptx_wap_liqu_export_nodes = calc_wap_ptx_liquef_export_ports(n, export_nodes)[0]
            
            #supply chain marginal prices
            h2_wap_for_ptx = calc_wap_h2_for_ptx(n)[0]
            ptx_wap_prod = calc_wap_ptx_prod(n)[0]
            ptx_wap_liqu = calc_wap_ptx_liquef(n)[0]
            ptx_wap_exp = calc_wap_ptx_exp(n)[0]
            ptx_wap_imp = calc_wap_ptx_imp(n)[0]
            ptx_wap_evap = calc_wap_ptx_evap(n)[0]

            #supply chain quantities 
            h2_qty_for_ptx = calc_wap_h2_for_ptx(n)[1]
            ptx_qty_exp = calc_wap_ptx_exp(n)[1]
            ptx_qty_prod = calc_wap_ptx_prod(n)[1]
            ptx_qty_liqu = calc_wap_ptx_liquef(n)[1]
            ptx_qty_exp = calc_wap_ptx_exp(n)[1]
            ptx_qty_imp = calc_wap_ptx_imp(n)[1]
            
            exp_shares = pd.Series(np.zeros(len(exp_ports_all)), index=exp_ports_all)
            exp_shares_val = calc_export_shares(n)
            exp_shares.loc[exp_shares_val.index] = exp_shares_val.values     

    
        exp_dict = {}

        for exp_p in exp_ports_all:
            # exp_dict[exp_p+' share'] = exp_shares[exp_p]
            node = exp_p.split(' ')[0]
            exp_dict[exp_p+ ' solar cap'] = n.generators.loc[(n.generators.bus == node) & (n.generators.carrier == 'solar'), 'p_nom_opt'].item()
            exp_dict[exp_p+' onwind cap'] = n.generators.loc[(n.generators.bus == node) & (n.generators.carrier == 'onwind'), 'p_nom_opt'].item()
            if 'onwind2' in n.generators.carrier.unique():
                exp_dict[exp_p+' onwind2 cap'] = n.generators.loc[(n.generators.bus == node) & (n.generators.carrier == 'onwind2'), 'p_nom_opt'].item()
            if 'offwind' in n.generators.carrier.unique():
                exp_dict[exp_p+' offwind cap'] = n.generators.loc[(n.generators.bus == node) & (n.generators.carrier == 'offwind'), 'p_nom_opt'].item()
            if 'offwind2' in n.generators.carrier.unique():
                exp_dict[exp_p+' offwind2 cap'] = n.generators.loc[(n.generators.bus == node) & (n.generators.carrier == 'offwind2'), 'p_nom_opt'].item()
            if 'offwind-ac' in n.generators.carrier.unique():
                if n.generators.loc[(n.generators.bus == node) & (n.generators.carrier == 'offwind-ac'), 'p_nom_opt'].size == 0:
                    exp_dict[exp_p+' offwind-ac cap'] = 0
                else:
                    exp_dict[exp_p+' offwind-ac cap'] = n.generators.loc[(n.generators.bus == node) & (n.generators.carrier == 'offwind-ac'), 'p_nom_opt'].item()
            if 'offwind-dc' in n.generators.carrier.unique():
                if n.generators.loc[(n.generators.bus == node) & (n.generators.carrier == 'offwind-dc'), 'p_nom_opt'].size == 0:
                    exp_dict[exp_p+' offwind-dc cap'] = 0
                else:
                    exp_dict[exp_p+' offwind-dc cap'] = n.generators.loc[(n.generators.bus == node) & (n.generators.carrier == 'offwind-dc'), 'p_nom_opt'].item()
            if 'csp' in n.generators.carrier.unique():
                exp_dict[exp_p+' csp cap'] = n.generators.loc[(n.generators.bus == node) & (n.generators.carrier == 'csp'), 'p_nom_opt'].item()
            if 'rooftop-solar' in n.generators.carrier.unique():
                exp_dict[exp_p+' rooftop-solar cap'] = n.generators.loc[(n.generators.bus == node) & (n.generators.carrier == 'rooftop-solar'), 'p_nom_opt'].item()

            if exp_p in exp_ports:
                stripped_name = exp_p.strip(' ship loading (exp)')
                exp_dict[exp_p+' share'] = exp_shares[exp_p]
                exp_dict[exp_p+' electrolyzer cap'] = n.links.filter(like=node, axis=0).loc[n.links.carrier == 'H2 Electrolysis', 'p_nom_opt'].item()
                exp_dict[exp_p+' electrolyzer cf'] = n.links_t.p0.filter(like=node).filter(like='Electrolysis').sum().sum()* n.snapshot_weightings.iloc[0, 0] / (exp_dict[exp_p+' electrolyzer cap'] * 8760)
                exp_dict[exp_p+' ptx_WAP'] = (n.buses_t.marginal_price[f"{stripped_name} berth (exp)"] * n.links_t.p1[f"{stripped_name} ship loading (exp)"]).sum() / n.links_t.p1[f"{stripped_name} ship loading (exp)"].sum() / 1e3
                if 'lnh3' in f:
                    exp_dict[exp_p+' H2_WAP'] = (n.buses_t.marginal_price[f"{stripped_name} H2"] * n.links_t.p3[f"{stripped_name} Haber-Bosch"] ).sum()/ (n.links_t.p3[f"{stripped_name} Haber-Bosch"]).sum() * 33.3 / 1e3
                elif 'lh2' in f:
                    exp_dict[exp_p+' H2_WAP'] = (n.buses_t.marginal_price[f"{stripped_name} H2"] * n.links_t.p0[f"{stripped_name} H2 liquefaction"] ).sum()/ (n.links_t.p0[f"{stripped_name} H2 liquefaction"]).sum() * 33.3 / 1e3


        #renewable capacities
        solar_cap = n.generators.loc[n.generators.carrier == 'solar', 'p_nom_opt'].sum()
        onwind_cap = n.generators.loc[n.generators.carrier == 'onwind', 'p_nom_opt'].sum()
        onwind2_cap = n.generators.loc[n.generators.carrier == 'onwind2', 'p_nom_opt'].sum()
        offwind_cap = n.generators.loc[n.generators.carrier == 'offwind', 'p_nom_opt'].sum()
        offwind2_cap = n.generators.loc[n.generators.carrier == 'offwind2', 'p_nom_opt'].sum()
        roof_solar_cap = n.generators.loc[n.generators.carrier == 'rooftop-solar', 'p_nom_opt'].sum()
        csp_cap = n.generators.loc[n.generators.carrier == 'csp', 'p_nom_opt'].sum()


        # geothermal usage
        geothermal_sh = calc_geothermal_share(n)


        #electrolyzer capacities and capacity factor
        elec_cap = n.links.filter(like='Electrolysis', axis=0).p_nom_opt.sum()
        elec_cf = n.links_t.p0.filter(like='Electrolysis').sum().sum()*n.snapshot_weightings.iloc[0, 0] / (elec_cap * 8760)


        #pipeline capa
        h2_pipeline_cap = calc_h2_pipeline_cap(n)
        nh3_pipeline_cap = calc_nh3_pipeline_cap(n)
        meoh_pipeline_cap = calc_meoh_pipeline_cap(n)
        co2_pipeline_cap = calc_co2_pipeline_cap(n)


        #storage capacities
        battery_cap = calc_batt_capa(n)
        uhs_cap = calc_uhs_capa(n)
        ahs_cap = calc_ahs_capa(n)
        uco2s_cap = calc_uco2s_capa(n)
        aco2s_cap = calc_aco2s_capa(n)
        anh3s_cap_exp = calc_anh3s_capa_exp(n)
        anh3s_cap_imp = calc_anh3s_capa_imp(n)
        ameohs_cap_exp = calc_ameohs_capa_exp(n)
        ameohs_cap_imp = calc_ameohs_capa_imp(n)
        


        #electricity and energy mix
        elec_mix = calc_elec_mix(n).sort_index().to_string() #relative
        ener_mix = calc_energy_mix(n).sort_index().to_string() #TWh


        # #emissions
        emissions = calc_emissions(n) /1e6 #Mt
        emissions_mp = n.buses_t.marginal_price.filter(like='atmosphere').squeeze().mean()
        

        #Create row for summary df
        summary_general = pd.DataFrame(data={
                    #general
                    'network':[n_path],
                    'network_name': ["n_{0}_{1}_{2}_{3}".format(year, i_rate, scen, q)],
                    'year':[int(year)],
                    'scenario':[scen],
                    'export_quantity':[int(q)],
                    'export_profile':[export_profile],

                    #ptx export related
                    'system_costs':[system_costs],
                    'system_costs_add_ex':[system_costs_corr],
                    'absolut_system_costs':[system_costs if int(year) == 2030 else system_costs_corr],
                    'exp_h2_cost_norm':[hydrogen_costs],
                    'exp_h2_cost_norm_add_ex':[hydrogen_costs_corr],
                    #----------
                    'h2_wap':[h2_wap],
                    'h2_for_ptx_cost_mp_export_nodes':[h2_wap_for_ptx_export_nodes],
                    'prod_ptx_cost_mp_export_nodes':[ptx_wap_prod_export_nodes],
                    'liqu_ptx_cost_mp_export_nodes':[ptx_wap_liqu_export_nodes],
                    #----------
                    'h2_for_ptx_cost_mp':[h2_wap_for_ptx],
                    'prod_ptx_cost_mp':[ptx_wap_prod],
                    'liqu_ptx_cost_mp':[ptx_wap_liqu],
                    'exp_ptx_cost_mp':[ptx_wap_exp],
                    'imp_ptx_cost_mp':[ptx_wap_imp],
                    'evap_ptx_cost_mp':[ptx_wap_evap],
                    'electrolyzer_cap':elec_cap,
                    'electrolyzer_cf':elec_cf,

                    #storage capacities
                    'battery_cap':battery_cap,
                    'uhs_cap':uhs_cap,
                    'ahs_cap':ahs_cap,
                    'uco2s_cap':uco2s_cap,
                    'aco2s_cap':aco2s_cap,
                    'anh3s_cap_exp':anh3s_cap_exp,
                    'anh3s_cap_imp':anh3s_cap_imp,
                    'ameohs_cap_exp':ameohs_cap_exp,
                    'ameohs_cap_imp':ameohs_cap_imp,
                    
                    #pipeline capa
                    'h2_pipeline_cap':h2_pipeline_cap,
                    'nh3_pipeline_cap':nh3_pipeline_cap,
                    'meoh_pipeline_cap':meoh_pipeline_cap,
                    'co2_pipeline_cap':co2_pipeline_cap,

                    #energy demand
                    'ptx_demand':ptx_demand,

                    #supply chain quantities 
                    'h2_for_ptx_qty':[h2_qty_for_ptx],
                    'ptx_qty_prod':[ptx_qty_prod],
                    'ptx_qty_liqu':[ptx_qty_liqu],
                    'ptx_qty_exp':[ptx_qty_exp],
                    'ptx_qty_imp':[ptx_qty_imp],

                    #RES related
                    'solar_cap': solar_cap,
                    'onwind_cap':onwind_cap,
                    'onwind2_cap':onwind2_cap,
                    'offwind_cap':offwind_cap,
                    'offwind2_cap':offwind2_cap,
                    'roof_solar_cap':roof_solar_cap,
                    'csp_cap':csp_cap,
                    'electricity_mix_rel':elec_mix,
                    'energy_mix_abs':ener_mix,
                    'curtailment':curtailment,

                    # cap shares related 
                    'geothermal_sh' : geothermal_sh,

                    #local markets related
                    'local_elec_wap':elec_wap,
                    'local_h2_wap':h2_wap,
                    'demand':demand,
                    'local_ac_demand':[ac_demand],
                    'loca_h2_demand':[h2_demand],
                    'costs-demand-ratio':[system_costs / demand / 1e6],

                    # #emission related
                    'emissions':emissions,
                    'emissions_mp':emissions_mp,
                    })
        summary_exp = pd.DataFrame(data={k:v for (k,v) in exp_dict.items()}, index=summary_general.index)
        summary_n = pd.concat([summary_general, summary_exp], axis=1)
        summary = pd.concat([summary, summary_n]).fillna(0)
        # sort_dict = {'BS':0, 'AP':1, 'NZ':2}
        # summary = summary.sort_values(['year', 'scenario', 'export_quantity']).sort_values(by='scenario', key= lambda k: k.map(sort_dict), kind='mergesort')

        # Adding RES expansion columns
        summary['additional_system_costs'] = 0  # Initialize with default value 0
        summary['solar_cap_expansion'] = 0  # Initialize with default value 0
        summary['onwind_cap_expansion'] = 0  # Initialize with default value 0
        summary['onwind2_cap_expansion'] = 0  # Initialize with default value 0
        summary['offwind_cap_expansion'] = 0  # Initialize with default value 0
        summary['offwind2_cap_expansion'] = 0  # Initialize with default value 0
        summary['roof_solar_cap_expansion'] = 0  # Initialize with default value 0
        summary['csp_cap_expansion'] = 0  # Initialize with default value 0

        # Filtering rows where 'export_quantity' is not equal to 0
        non_zero_export_quantity = summary['export_quantity'] != 0
        # Calculate 'additional_system_costs' for non-zero 'export_quantity' based on unique scenario and year
        for scenario, year in summary.loc[non_zero_export_quantity, ['scenario', 'year']].drop_duplicates().itertuples(index=False):
            scenario_year_filter = (summary['scenario'] == scenario) & (summary['year'] == year)

            ref_abs_system_costs = summary.loc[scenario_year_filter & (summary['export_quantity'] == 0), 'absolut_system_costs'].iloc[0]
            summary.loc[scenario_year_filter & non_zero_export_quantity, 'additional_system_costs'] = summary.loc[scenario_year_filter & non_zero_export_quantity, 'absolut_system_costs'] - ref_abs_system_costs

            ref = summary.loc[scenario_year_filter & (summary['export_quantity'] == 0), 'solar_cap'].iloc[0]
            summary.loc[scenario_year_filter & non_zero_export_quantity, 'solar_cap_expansion'] = summary.loc[scenario_year_filter & non_zero_export_quantity, 'solar_cap'] - ref

            ref = summary.loc[scenario_year_filter & (summary['export_quantity'] == 0), 'onwind_cap'].iloc[0]
            summary.loc[scenario_year_filter & non_zero_export_quantity, 'onwind_cap_expansion'] = summary.loc[scenario_year_filter & non_zero_export_quantity, 'onwind_cap'] - ref

            ref = summary.loc[scenario_year_filter & (summary['export_quantity'] == 0), 'onwind2_cap'].iloc[0]
            summary.loc[scenario_year_filter & non_zero_export_quantity, 'onwind2_cap_expansion'] = summary.loc[scenario_year_filter & non_zero_export_quantity, 'onwind2_cap'] - ref

            ref = summary.loc[scenario_year_filter & (summary['export_quantity'] == 0), 'offwind_cap'].iloc[0]
            summary.loc[scenario_year_filter & non_zero_export_quantity, 'offwind_cap_expansion'] = summary.loc[scenario_year_filter & non_zero_export_quantity, 'offwind_cap'] - ref

            ref = summary.loc[scenario_year_filter & (summary['export_quantity'] == 0), 'offwind2_cap'].iloc[0]
            summary.loc[scenario_year_filter & non_zero_export_quantity, 'offwind2_cap_expansion'] = summary.loc[scenario_year_filter & non_zero_export_quantity, 'offwind2_cap'] - ref

            ref = summary.loc[scenario_year_filter & (summary['export_quantity'] == 0), 'roof_solar_cap'].iloc[0]
            summary.loc[scenario_year_filter & non_zero_export_quantity, 'roof_solar_cap_expansion'] = summary.loc[scenario_year_filter & non_zero_export_quantity, 'roof_solar_cap'] - ref

            ref = summary.loc[scenario_year_filter & (summary['export_quantity'] == 0), 'csp_cap'].iloc[0]
            summary.loc[scenario_year_filter & non_zero_export_quantity, 'csp_cap_expansion'] = summary.loc[scenario_year_filter & non_zero_export_quantity, 'csp_cap'] - ref
    try:
        os.mkdir(os.getcwd()+'/pypsa-earth-sec/outputs/{}'.format(run_name))
        os.mkdir(os.getcwd()+'/pypsa-earth-sec/outputs/{}/maps'.format(run_name))
        os.mkdir(os.getcwd()+'/pypsa-earth-sec/outputs/{}/tables'.format(run_name))
        summary.to_csv(os.getcwd()+'/pypsa-earth-sec/outputs/{}/tables/summary.csv'.format(run_name))
        os.mkdir(os.getcwd()+'/pypsa-earth-sec/outputs/{}/plots'.format(run_name))
        os.mkdir(os.getcwd()+'/pypsa-earth-sec/outputs/{}/plots_scenarios'.format(run_name))
        
    except:
        summary.to_csv(os.getcwd()+'/pypsa-earth-sec/outputs/{}/tables/summary.csv'.format(run_name))
    return summary


# def create_summary_df(run_name):
#     summary = pd.DataFrame()
#     path = os.getcwd()+'/pypsa-earth-sec/results/{}/postnetworks'.format(run_name)
#     exp_ports_all = []

#     # Define a function to extract both text and number
#     def extract_sort_key(filepath):
#         match = re.search(r'(AB)_(\d+)export', filepath)
#         if match:
#             text = match.group(1)
#             number = int(match.group(2))
#             return (text, number)
#         return ('', 0)

#     # Sort based on both text and number
#     file_list = sorted(os.listdir(path), key=extract_sort_key)

#     # file_list = sorted(os.listdir(path))
#     # file_list = sorted(os.listdir(path), key=lambda x: int(re.search(r'_\d+(?=\D)', x).group(0)[1:]))

#     for i, f in enumerate(file_list):
#     # for f in os.listdir(path):
#         n_path = path+'/{}'.format(f)
#         q = int(f.split('_')[-3].split('e')[0])
#         scen = f.split('_')[-4]
#         year = f.split('_')[-6]
#         i_rate = f.split('_')[-5]

#         n = pypsa.Network(n_path)

#         #system costs
#         system_costs = n.objective
#         system_costs_corr = system_costs + n.objective_constant
#         if q == 0:
#             system_costs_no_exports= system_costs
#             system_costs_no_exports_corr = system_costs_corr

#         #average costs of exported hydrogen
#         hydrogen_costs = (system_costs - system_costs_no_exports) / (q*1e9) * 33.3
#         hydrogen_costs_corr = (system_costs_corr - system_costs_no_exports_corr) / (q*1e9) * 33.3

#         #local markt prices
#         elec_wap = calc_wap_elec(n)
#         h2_wap = calc_wap_h2(n)
        
#         #energy demand
#         demand = calc_demand(n) + q
#         ac_demand = calc_ac_demand(n)
#         h2_demand = calc_h2_demand(n)

#         #curtailment
#         curtailment = calc_curtailment(n)
        
#         exp_ports = n.links.filter(like='export', axis=0).index

#         #export port shares and export h2 price according to MP
#         if '_0export' in f:
#             hydrogen_wap_exp = 0
#             hydrogen_wap_imp = 0
#             exp_shares = pd.Series(np.zeros(len(exp_ports)), index=exp_ports)
#             if i < len(file_list) - 1:
#                 # Get the export ports of the next file (f+1)
#                 next_f = file_list[i + 1]
#                 # if '_0export' in next_f:
#                 #     next_f = file_list[i + 2]
#                 #     next_n_path = path + '/{}'.format(next_f)
#                 #     next_n = pypsa.Network(next_n_path)
#                 #     exp_ports_all = next_n.links.filter(like='export', axis=0).index
#                 # else:
#                 next_n_path = path + '/{}'.format(next_f)
#                 next_n = pypsa.Network(next_n_path)
#                 exp_ports_all = next_n.links.filter(like='export', axis=0).index
#             # if q == 0:
#         #     hydrogen_wap_exp = 0
#         #     exp_shares = pd.Series(np.zeros(len(exp_ports)), index=exp_ports)
#         #     exp_ports_all = exp_ports
#         # #     exp_ports_0 = exp_ports
#         # # elif q == 1 or q == 10:
#         # #     hydrogen_wap_exp = calc_wap_h2_exp(n)
#         # #     exp_shares = calc_export_shares(n)
#         # #     exp_ports = exp_ports_0
#         else:
#             hydrogen_wap_exp = calc_wap_h2_exp(n)
#             hydrogen_wap_imp = calc_wap_h2_imp(n)
#             exp_shares = pd.Series(np.zeros(len(exp_ports_all)), index=exp_ports_all)
#             exp_shares_val = calc_export_shares(n)
#             exp_shares.loc[exp_shares_val.index] = exp_shares_val.values        
        
#         exp_dict = {}

#         for exp_p in exp_ports_all:
#             # exp_dict[exp_p+' share'] = exp_shares[exp_p]
#             node = exp_p.split(' ')[0]
#             exp_dict[exp_p+ ' solar cap'] = n.generators.loc[(n.generators.bus == node) & (n.generators.carrier == 'solar'), 'p_nom_opt'].item()
#             exp_dict[exp_p+' onwind cap'] = n.generators.loc[(n.generators.bus == node) & (n.generators.carrier == 'onwind'), 'p_nom_opt'].item()
#             exp_dict[exp_p+' onwind2 cap'] = n.generators.loc[(n.generators.bus == node) & (n.generators.carrier == 'onwind2'), 'p_nom_opt'].item()
#             if 'UAE' not in run_name:
#                 exp_dict[exp_p+' offwind cap'] = n.generators.loc[(n.generators.bus == node) & (n.generators.carrier == 'offwind'), 'p_nom_opt'].item()
#                 exp_dict[exp_p+' offwind2 cap'] = n.generators.loc[(n.generators.bus == node) & (n.generators.carrier == 'offwind2'), 'p_nom_opt'].item()
#             exp_dict[exp_p+' csp cap'] = n.generators.loc[(n.generators.bus == node) & (n.generators.carrier == 'csp'), 'p_nom_opt'].item()
#             exp_dict[exp_p+' rooftop-solar cap'] = n.generators.loc[(n.generators.bus == node) & (n.generators.carrier == 'rooftop-solar'), 'p_nom_opt'].item()

#             if exp_p in exp_ports:
#                 exp_dict[exp_p+' share'] = exp_shares[exp_p]
#                 exp_dict[exp_p+' electrolyzer cap'] = n.links.filter(like=node, axis=0).loc[n.links.carrier == 'H2 Electrolysis', 'p_nom_opt'].item()
#                 exp_dict[exp_p+' electrolyzer cf'] = n.links_t.p0.filter(like=node).filter(like='Electrolysis').sum().sum()*3 / (exp_dict[exp_p+' electrolyzer cap'] * 8760)
#                 exp_dict[exp_p+' H2_WAP'] = (n.buses_t.marginal_price[exp_p.strip(' export')] * n.links_t.p0[exp_p]).sum() / n.links_t.p0[exp_p].sum() * 33.3 / 1e3

#         #renewable capacities
#         solar_cap = n.generators.loc[n.generators.carrier == 'solar', 'p_nom_opt'].sum()
#         onwind_cap = n.generators.loc[n.generators.carrier == 'onwind', 'p_nom_opt'].sum()
#         onwind2_cap = n.generators.loc[n.generators.carrier == 'onwind2', 'p_nom_opt'].sum()
#         offwind_cap = n.generators.loc[n.generators.carrier == 'offwind', 'p_nom_opt'].sum()
#         offwind2_cap = n.generators.loc[n.generators.carrier == 'offwind2', 'p_nom_opt'].sum()
#         roof_solar_cap = n.generators.loc[n.generators.carrier == 'rooftop-solar', 'p_nom_opt'].sum()
#         csp_cap = n.generators.loc[n.generators.carrier == 'csp', 'p_nom_opt'].sum()

#         # geothermal usage
#         geothermal_sh = calc_geothermal_share(n)

#         #electrolyzer capacities and capacity factor
#         elec_cap = n.links.filter(like='Electrolysis', axis=0).p_nom_opt.sum()
#         elec_cf = n.links_t.p0.filter(like='Electrolysis').sum().sum()*3 / (elec_cap * 8760)

#         #pipeline capa
#         pipeline_cap = calc_pipeline_cap(n)

#         #storage capacities
#         battery_cap = calc_batt_capa(n)
#         uhs_cap = calc_uhs_capa(n)

#         #electricity and energy mix
#         elec_mix = calc_elec_mix(n).sort_index().to_string() #relative
#         ener_mix = calc_energy_mix(n).sort_index().to_string() #TWh

#         # #emissions
#         emissions = calc_emissions(n) /1e6 #Mt
#         emissions_mp = n.buses_t.marginal_price.filter(like='atmosphere').squeeze().mean()
        
#         #Create row for summary df
#         summary_general = pd.DataFrame(data={
#                     #general
#                     'network':[n_path],
#                     'network_name': ["n_{0}_{1}_{2}_{3}".format(year, i_rate, scen, q)],
#                     'year':[int(year)],
#                     'scenario':[scen],
#                     'export_quantity':[int(q)],

#                     #hydrogen export related
#                     'system_costs':[system_costs],
#                     'system_costs_add_ex':[system_costs_corr],
#                     'absolut_system_costs':[system_costs if int(year) == 2030 else system_costs_corr],
#                     'exp_h2_cost_norm':[hydrogen_costs],
#                     'exp_h2_cost_norm_add_ex':[hydrogen_costs_corr],
#                     'exp_h2_cost_mp':[hydrogen_wap_exp],
#                     'imp_h2_cost_mp':[hydrogen_wap_imp],
#                     'electrolyzer_cap':elec_cap,
#                     'electrolyzer_cf':elec_cf,
#                     'uhs_cap':uhs_cap,
#                     'pipeline_cap':pipeline_cap,

#                     #RES related
#                     'solar_cap': solar_cap,
#                     'onwind_cap':onwind_cap,
#                     'onwind2_cap':onwind2_cap,
#                     'offwind_cap':offwind_cap,
#                     'offwind2_cap':offwind2_cap,
#                     'roof_solar_cap':roof_solar_cap,
#                     'csp_cap':csp_cap,
#                     'battery_cap':battery_cap,
#                     'electricity_mix_rel':elec_mix,
#                     'energy_mix_abs':ener_mix,
#                     'curtailment':curtailment,

#                     # cap shares related 
#                     'geothermal_sh' : geothermal_sh,

#                     #local markets related
#                     'elec_wap':elec_wap,
#                     'h2_wap':h2_wap,
#                     'demand':demand,
#                     'ac_demand':[ac_demand],
#                     'h2_demand':[h2_demand],
#                     'costs-demand-ratio':[system_costs / demand / 1e6],

#                     # #emission related
#                     'emissions':emissions,
#                     'emissions_mp':emissions_mp,
#                     })
#         summary_exp = pd.DataFrame(data={k:v for (k,v) in exp_dict.items()}, index=summary_general.index)
#         summary_n = pd.concat([summary_general, summary_exp], axis=1)
#         summary = pd.concat([summary, summary_n]).fillna(0)
#         # sort_dict = {'BS':0, 'AP':1, 'NZ':2}
#         # summary = summary.sort_values(['year', 'scenario', 'export_quantity']).sort_values(by='scenario', key= lambda k: k.map(sort_dict), kind='mergesort')

#         # Adding RES expansion columns
#         summary['additional_system_costs'] = 0  # Initialize with default value 0
#         summary['solar_cap_expansion'] = 0  # Initialize with default value 0
#         summary['onwind_cap_expansion'] = 0  # Initialize with default value 0
#         summary['onwind2_cap_expansion'] = 0  # Initialize with default value 0
#         summary['offwind_cap_expansion'] = 0  # Initialize with default value 0
#         summary['offwind2_cap_expansion'] = 0  # Initialize with default value 0
#         summary['roof_solar_cap_expansion'] = 0  # Initialize with default value 0
#         summary['csp_cap_expansion'] = 0  # Initialize with default value 0

#         # Filtering rows where 'export_quantity' is not equal to 0
#         non_zero_export_quantity = summary['export_quantity'] != 0
#         # Calculate 'additional_system_costs' for non-zero 'export_quantity' based on unique scenario and year
#         for scenario, year in summary.loc[non_zero_export_quantity, ['scenario', 'year']].drop_duplicates().itertuples(index=False):
#             scenario_year_filter = (summary['scenario'] == scenario) & (summary['year'] == year)

#             ref_abs_system_costs = summary.loc[scenario_year_filter & (summary['export_quantity'] == 0), 'absolut_system_costs'].iloc[0]
#             summary.loc[scenario_year_filter & non_zero_export_quantity, 'additional_system_costs'] = summary.loc[scenario_year_filter & non_zero_export_quantity, 'absolut_system_costs'] - ref_abs_system_costs

#             ref = summary.loc[scenario_year_filter & (summary['export_quantity'] == 0), 'solar_cap'].iloc[0]
#             summary.loc[scenario_year_filter & non_zero_export_quantity, 'solar_cap_expansion'] = summary.loc[scenario_year_filter & non_zero_export_quantity, 'solar_cap'] - ref

#             ref = summary.loc[scenario_year_filter & (summary['export_quantity'] == 0), 'onwind_cap'].iloc[0]
#             summary.loc[scenario_year_filter & non_zero_export_quantity, 'onwind_cap_expansion'] = summary.loc[scenario_year_filter & non_zero_export_quantity, 'onwind_cap'] - ref

#             ref = summary.loc[scenario_year_filter & (summary['export_quantity'] == 0), 'onwind2_cap'].iloc[0]
#             summary.loc[scenario_year_filter & non_zero_export_quantity, 'onwind2_cap_expansion'] = summary.loc[scenario_year_filter & non_zero_export_quantity, 'onwind2_cap'] - ref

#             ref = summary.loc[scenario_year_filter & (summary['export_quantity'] == 0), 'offwind_cap'].iloc[0]
#             summary.loc[scenario_year_filter & non_zero_export_quantity, 'offwind_cap_expansion'] = summary.loc[scenario_year_filter & non_zero_export_quantity, 'offwind_cap'] - ref

#             ref = summary.loc[scenario_year_filter & (summary['export_quantity'] == 0), 'offwind2_cap'].iloc[0]
#             summary.loc[scenario_year_filter & non_zero_export_quantity, 'offwind2_cap_expansion'] = summary.loc[scenario_year_filter & non_zero_export_quantity, 'offwind2_cap'] - ref

#             ref = summary.loc[scenario_year_filter & (summary['export_quantity'] == 0), 'roof_solar_cap'].iloc[0]
#             summary.loc[scenario_year_filter & non_zero_export_quantity, 'roof_solar_cap_expansion'] = summary.loc[scenario_year_filter & non_zero_export_quantity, 'roof_solar_cap'] - ref

#             ref = summary.loc[scenario_year_filter & (summary['export_quantity'] == 0), 'csp_cap'].iloc[0]
#             summary.loc[scenario_year_filter & non_zero_export_quantity, 'csp_cap_expansion'] = summary.loc[scenario_year_filter & non_zero_export_quantity, 'csp_cap'] - ref
#     try:
#         os.mkdir(os.getcwd()+'/pypsa-earth-sec/outputs/{}'.format(run_name))
#         os.mkdir(os.getcwd()+'/pypsa-earth-sec/outputs/{}/maps'.format(run_name))
#         os.mkdir(os.getcwd()+'/pypsa-earth-sec/outputs/{}/tables'.format(run_name))
#         summary.to_csv(os.getcwd()+'/pypsa-earth-sec/outputs/{}/tables/summary.csv'.format(run_name))
#         os.mkdir(os.getcwd()+'/pypsa-earth-sec/outputs/{}/plots'.format(run_name))
        
#     except:
#         summary.to_csv(os.getcwd()+'/pypsa-earth-sec/outputs/{}/tables/summary.csv'.format(run_name))
#     return summary

def get_summary_df(run_name, update_table=True):
    try:
        df = pd.read_csv(os.getcwd()+'/pypsa-earth-sec/outputs/{}/tables/summary.csv'.format(run_name))
        if update_table == True:
            print('Updating existing summary dataframe for given run {}'.format(run_name))
            df = create_summary_df(run_name)
    except:
        print('Creating summary dataframe for given run {}'.format(run_name))
        df = create_summary_df(run_name)
    return df

# def get_networks(run_name):
#     networks = {}
#     path = os.getcwd()+'/pypsa-earth-sec/results/{}/postnetworks'.format(run_name)
#     for f in os.listdir(path):
#         n_path = path+'/{}'.format(f)
#         q = int(f.split('_')[-1].split('e')[0])
#         scen = f.split('_')[-2]
#         year = int(f.split('_')[-4])
#         n = pypsa.Network(n_path)

#         networks[year] = {}
#         networks[year][scen] = {}
#         networks[year][scen][q] = n
#     return networks

def get_networks(summary):
    summary = summary.reset_index()
    networks = {}
    for y in summary.year.unique():
        networks[y] = {}
        for s in summary.scenario.unique():
            networks[y][s] = {}
            summary_y_s = summary.loc[(summary.year == y) & (summary.scenario == s)]
            for q in summary_y_s.export_quantity.unique():
                n_path = summary_y_s.loc[summary_y_s.export_quantity == q, 'network'].item()
                n = pypsa.Network(n_path)
                networks[y][s][q] = n
    return networks

def get_networks_for_maps(summary):
    networks = {}
    for name in summary.network_name:
        n_path = summary.loc[summary.network_name == name, 'network'].item()
        n = pypsa.Network(n_path)
        networks[name] = n
    return networks

def get_network(df, year=2030, scenario='AP', quantity=0):
    df = df.reset_index()
    path = df.loc[(df.year == year) & (df.scenario == scenario) & (df.export_quantity == quantity), 'network'].item()
    n = pypsa.Network(path)
    return n


def plot_additional_sytsem_costs(summary, run_name, colors):
    delivery_schedule = run_name.split('_')[2]
    fig, (ax, ax2) = plt.subplots(2,1)
    fig.set_size_inches(10, 10)    
    costs_y = summary.reset_index()
    color_dict = {'BS': colors[0], 'AP':colors[1], 'NZ':colors[2]}
    scen_dict = {'BS': 'Conservative', 'AP':'Realistic', 'NZ':'Optimistic'}


    for s in costs_y.scenario.unique():
        costs_y_s = costs_y.loc[(costs_y.scenario == s)&(costs_y.year == 2030)]

        #ax.fill_between(min.export_quantity, min.price, max.price, alpha=.3)
        ax.plot(costs_y_s.export_quantity, costs_y_s.additional_system_costs/1e9, linestyle='--', linewidth=1, label='2030 ' + scen_dict[s], color=color_dict[s], marker="o", zorder=5)


    for s in costs_y.scenario.unique():
        costs_y_s = costs_y.loc[(costs_y.scenario == s)&(costs_y.year == 2050)]
        
        #ax.fill_between(min.export_quantity, min.price, max.price, alpha=.3)
        ax2.plot(costs_y_s.export_quantity, costs_y_s.additional_system_costs/1e9, linestyle='--', linewidth=1, label='2050 ' + scen_dict[s], color=color_dict[s], marker="o", zorder=5)

    # ax.set_xlabel('Export quantity steps in TWh')
    # ax.set_ylabel('Total System Costs in B€')
    # ax.set_xticks(costs_y_s.export_quantity)
    # ax2.set_xlabel('')
    fig.text(0.5, 0.05, 'Different hydrogen export quantities [TWh]', ha='center')
    fig.text(0.08, 0.5, 'Annualized additional system expansion costs [Bn €]', va='center', rotation='vertical')
    ax.legend()
    ax2.legend()
    plt.suptitle('Annualized system expansion costs | All scenarios | {}'.format(delivery_schedule), x=0.5, y=0.94, ha='center')
    plt.savefig(os.getcwd()+'/pypsa-earth-sec/outputs/{}/plots/system_expansion_costs_{}.png'.format(run_name, run_name.split('_')[0]), bbox_inches='tight', dpi=300)
    plt.close()



def plot_additional_sytsem_expansion_costs(full_summary, run_name, colors):
    df=full_summary.copy()
    delivery_schedule = run_name.split('_')[2]
    fig, (ax, ax2) = plt.subplots(2,1)
    fig.set_size_inches(10, 10)    
    costs_y = df.reset_index()


    # color_dict = {'BS': colors[0], 'AP':colors[1], 'NZ':colors[2]}
    # scen_dict = {'BS': 'Conservative', 'AP':'Realistic', 'NZ':'Optimistic'}
    color_dict = {'free': colors[0], 'nh3_free':colors[1], 'h2_free':colors[2], 'at_port':colors[2]}
    scen_dict = {'free': 'free', 'nh3_free':'nh3_free', 'h2_free':'h2_free', 'at_port':'at_port'}

    for s in costs_y.scenario.unique():
        costs_y_s = costs_y.loc[(costs_y.scenario == s)&(costs_y.year == 2030)]

        #ax.fill_between(min.export_quantity, min.price, max.price, alpha=.3)
        ax.plot(costs_y_s.export_quantity, costs_y_s.additional_system_costs/1e9, linestyle='--', linewidth=1, label='2030 ' + scen_dict[s], color=color_dict[s], marker="o", zorder=5)


    for s in costs_y.scenario.unique():
        costs_y_s = costs_y.loc[(costs_y.scenario == s)&(costs_y.year == 2050)]
        
        #ax.fill_between(min.export_quantity, min.price, max.price, alpha=.3)
        ax2.plot(costs_y_s.export_quantity, costs_y_s.additional_system_costs/1e9, linestyle='--', linewidth=1, label='2050 ' + scen_dict[s], color=color_dict[s], marker="o", zorder=5)

    # ax.set_xlabel('Export quantity steps in TWh')
    # ax.set_ylabel('Total System Costs in B€')
    # ax.set_xticks(costs_y_s.export_quantity)
    # ax2.set_xlabel('')
    fig.text(0.5, 0.05, 'Different hydrogen export quantities [TWh]', ha='center')
    fig.text(0.08, 0.5, 'Annualized additional system expansion costs [Bn €]', va='center', rotation='vertical')
    ax.legend()
    ax2.legend()
    plt.suptitle('Annualized system expansion costs | All scenarios | {}'.format(delivery_schedule), x=0.5, y=0.94, ha='center')
    plt.savefig(os.getcwd()+'/pypsa-earth-sec/outputs/{}/plots/system_expansion_costs_{}.png'.format(run_name, run_name.split('_')[0]), bbox_inches='tight', dpi=300)
    plt.close()


def plot_ptx_marginal_prices_export(full_summary, run_name, colors):
    df = full_summary.copy()
    delivery_schedule = run_name.split('_')[2]
    fig, (ax, ax2) = plt.subplots(2,1)
    fig.set_size_inches(10, 10)    
    costs_y = df.reset_index()
    color_dict = {'free': colors[0], 'nh3_free':colors[1], 'h2_free':colors[2], 'at_port':colors[2]}
    scen_dict = {'free': 'free', 'nh3_free':'nh3_free', 'h2_free':'h2_free', 'at_port':'at_port'}


    for s in costs_y.scenario.unique():
        costs_y_s = costs_y.loc[(costs_y.scenario == s)&(costs_y.year == 2030)&(costs_y.export_quantity != 0)].round(2)

        #ax.fill_between(min.export_quantity, min.price, max.price, alpha=.3)
        ax.plot(costs_y_s.export_quantity, costs_y_s.evap_ptx_cost_mp, linestyle='--', linewidth=1, label='2030 ' + scen_dict[s], color=color_dict[s], marker="o", zorder=5)


    for s in costs_y.scenario.unique():
        costs_y_s = costs_y.loc[(costs_y.scenario == s)&(costs_y.year == 2050)&(costs_y.export_quantity != 0)]
        
        #ax.fill_between(min.export_quantity, min.price, max.price, alpha=.3)
        ax2.plot(costs_y_s.export_quantity, costs_y_s.evap_ptx_cost_mp, linestyle='--', linewidth=1, label='2050 ' + scen_dict[s], color=color_dict[s], marker="o", zorder=5)

    # ax.set_xlabel('Export quantity steps in TWh')
    # ax.set_ylabel('Total System Costs in B€')
    # ax.set_xticks(costs_y_s.export_quantity)
    # ax2.set_xlabel('')
    fig.text(0.5, 0.05, 'Different PtX export quantities [TWh]', ha='center')
    fig.text(0.08, 0.5, 'Market prices of PtX export [€/MWh]', va='center', rotation='vertical')
    ax.legend()
    ax2.legend()
    plt.suptitle('Market prices of export hydrogen | All scenarios | {}'.format(delivery_schedule), x=0.5, y=0.94, ha='center')
    plt.savefig(os.getcwd()+'/pypsa-earth-sec/outputs/{}/plots/ptx_export_costs_{}.png'.format(run_name, run_name.split('_')[0]), bbox_inches='tight', dpi=300)
    plt.close()

def plot_H2_marginal_prices_export(summary, run_name, colors):
    delivery_schedule = run_name.split('_')[2]
    fig, (ax, ax2) = plt.subplots(2,1)
    fig.set_size_inches(10, 10)    
    costs_y = summary.reset_index()
    color_dict = {'BS': colors[0], 'AP':colors[1], 'NZ':colors[2]}
    scen_dict = {'BS': 'Conservative', 'AP':'Realistic', 'NZ':'Optimistic'}


    for s in costs_y.scenario.unique():
        costs_y_s = costs_y.loc[(costs_y.scenario == s)&(costs_y.year == 2030)&(costs_y.export_quantity != 0)].round(2)

        #ax.fill_between(min.export_quantity, min.price, max.price, alpha=.3)
        ax.plot(costs_y_s.export_quantity, costs_y_s.exp_h2_cost_mp, linestyle='--', linewidth=1, label='2030 ' + scen_dict[s], color=color_dict[s], marker="o", zorder=5)


    for s in costs_y.scenario.unique():
        costs_y_s = costs_y.loc[(costs_y.scenario == s)&(costs_y.year == 2050)&(costs_y.export_quantity != 0)]
        
        #ax.fill_between(min.export_quantity, min.price, max.price, alpha=.3)
        ax2.plot(costs_y_s.export_quantity, costs_y_s.exp_h2_cost_mp, linestyle='--', linewidth=1, label='2050 ' + scen_dict[s], color=color_dict[s], marker="o", zorder=5)

    # ax.set_xlabel('Export quantity steps in TWh')
    # ax.set_ylabel('Total System Costs in B€')
    # ax.set_xticks(costs_y_s.export_quantity)
    # ax2.set_xlabel('')
    fig.text(0.5, 0.05, 'Different hydrogen export quantities [TWh]', ha='center')
    fig.text(0.08, 0.5, 'Market prices of hydrogen at the export nodes [€/kg]', va='center', rotation='vertical')
    ax.legend()
    ax2.legend()
    plt.suptitle('Market prices of export hydrogen | All scenarios | {}'.format(delivery_schedule), x=0.5, y=0.94, ha='center')
    plt.savefig(os.getcwd()+'/pypsa-earth-sec/outputs/{}/plots/hydrogen_shadow_prices_{}.png'.format(run_name, run_name.split('_')[0]), bbox_inches='tight', dpi=300)
    plt.close()


def plot_average_h2_costs(summary):
    summary = summary.reset_index()
    for y in summary.year.unique():
        fig, ax = plt.subplots(1, 1)
        fig.set_size_inches(8, 6)    
        costs_y = summary.loc[summary.year == y]
        color_dict = {'BS': 'red', 'AP':'blue', 'NZ':'green'}
        scen_dict = {'BS': 'Conservative', 'AP':'Realistic', 'NZ':'Optimistic'}
        for s in summary.scenario.unique():
            costs_y_s = costs_y.loc[costs_y.scenario == s]
            if y == 2030:
                h2_costs = costs_y_s.exp_h2_cost_norm
            else:
                h2_costs = costs_y_s.exp_h2_cost_norm_add_ex
            ax.plot(costs_y_s.export_quantity, h2_costs, label=scen_dict[s], color=color_dict[s], linestyle='dashed', alpha=0.8, linewidth=0.8)
            ax.scatter(costs_y_s.export_quantity.iloc[1:], h2_costs.iloc[1:], color=color_dict[s], s=30)
        
        ax.set_xlabel('Export quantity steps in TWh', fontsize=14)
        ax.set_ylabel('Average normalized costs of\nexported hydrogen in €/kg', fontsize=14)
        ax.set_xticks(costs_y_s.export_quantity.iloc[1:])

        tick_labels = costs_y_s.export_quantity.iloc[1:].astype(str)
        tick_labels.iloc[1] = '\n' + tick_labels.iloc[1]
        ax.set_xticklabels(tick_labels)
        ax.set_xlim((0, costs_y.export_quantity.max()))
        
        ax.legend(loc='lower right')
        ax.tick_params(axis='both', which='major', labelsize=12)
        plt.tight_layout()
        run_name = summary.network.iloc[0].split('/')[-3]
        plt.savefig(os.getcwd()+'/pypsa-earth-sec/outputs/{}/plots/export_average_h2_costs_{}.png'.format(run_name, str(y)))

def plot_h2_mp_exp(summary):
    summary = summary.reset_index()
    for y in summary.year.unique():
        fig, ax = plt.subplots(1, 1)
        fig.set_size_inches(8, 6)    
        costs_y = summary.loc[summary.year == y]
        color_dict = {'BS': 'red', 'AP':'blue', 'NZ':'green'}
        scen_dict = {'BS': 'Conservative', 'AP':'Realistic', 'NZ':'Optimistic'}
        for s in summary.scenario.unique():
            costs_y_s = costs_y.loc[costs_y.scenario == s]
            h2_costs = costs_y_s.exp_h2_cost_mp
            
            ax.plot(costs_y_s.export_quantity, h2_costs, label=scen_dict[s], color=color_dict[s], linestyle='dashed', alpha=0.8, linewidth=0.8)
            ax.scatter(costs_y_s.export_quantity.iloc[1:], h2_costs.iloc[1:], color=color_dict[s], s=30)
        
        ax.set_xlabel('Export quantity steps in TWh', fontsize=14)
        ax.set_ylabel('Weighted average price of\nexported hydrogen in €/kg', fontsize=14)
        ax.set_xticks(costs_y_s.export_quantity.iloc[1:])

        tick_labels = costs_y_s.export_quantity.iloc[1:].astype(str)
        tick_labels.iloc[1] = '\n' + tick_labels.iloc[1]
        ax.set_xticklabels(tick_labels)
        ax.set_xlim((0, costs_y.export_quantity.max()))
        
        ax.legend(loc='lower right')
        ax.tick_params(axis='both', which='major', labelsize=12)
        plt.tight_layout()
        run_name = summary.network.iloc[0].split('/')[-3]
        plt.savefig(os.getcwd()+'/pypsa-earth-sec/outputs/{}/plots/export_h2_mp_{}.png'.format(run_name, str(y)))

def plot_electrolyzer_caps(elec_cap, run_name):
    delivery_schedule = run_name.split('_')[2]
    df = elec_cap.reset_index()
    for y in df.year.unique():
        fig, ax = plt.subplots(1, 1)
        fig.set_size_inches(8, 6)

        df_y = df.loc[df.year == y].drop('year', axis=1)
        df_y['electrolyzer_cap'] = df_y.electrolyzer_cap - df_y.filter(like='electrolyzer cap').sum(axis=1)
        df_y.rename({'electrolyzer_cap':'Electrolyzer capacity in other nodes'}, inplace=True, axis=1)
        df_y.set_index(['scenario', 'export_quantity']).plot.bar(stacked=True, ax=ax, cmap= custom_cmap(), zorder=5)

        ax.set_ylabel('Electrolyzer capacity in MW')
        ax.legend(bbox_to_anchor=(1,1))
    plt.suptitle('Electrolyzer capacity | All scenarios | {}'.format(delivery_schedule), x=0.5, y=0.94, ha='center')
    plt.savefig(os.getcwd()+'/pypsa-earth-sec/outputs/{}/plots/plot_electrolyzer_caps_{}.png'.format(run_name, str(y)), dpi=300, bbox_inches='tight')
    plt.close()

def plot_electrolyzer_cf(summary, run_name):
    delivery_schedule = run_name.split('_')[2]
    df = summary.filter(like='cf')
    df.reset_index(inplace=True)
    for y in df.year.unique():
        fig, ax = plt.subplots(1, 1)
        fig.set_size_inches(8, 6)

        df_y = df.loc[df.year == y].drop('year', axis=1)
        
        df_y.rename({'electrolyzer_cf':'Overall electrolyzer capacity factor'}, inplace=True, axis=1)
        df_y.set_index(['scenario', 'export_quantity']).plot.bar(ax=ax, cmap= custom_cmap(), zorder=5)

        ax.set_ylabel('Electrolyzer capacity factor')
        ax.legend(bbox_to_anchor=(1,1))
    plt.suptitle('Electrolyzer capacity factor | All scenarios | {}'.format(delivery_schedule), x=0.5, y=0.94, ha='center')
    plt.savefig(os.getcwd()+'/pypsa-earth-sec/outputs/{}/plots/plot_electrolyzer_cf_{}.png'.format(run_name, str(y)), dpi=300, bbox_inches='tight')
    plt.close()


def plot_h2_exports(ns, summary, sample_rate='W', scenario='AP'):
    summary = summary.reset_index()
    summary = summary.loc[summary.export_quantity > 0]
    ex_quantities={2030: list(summary.loc[summary.year ==2030, 'export_quantity'].unique()),
                    2050: list(summary.loc[summary.year ==2050, 'export_quantity'].unique())} # , 2050: [10, 100, 500, 1000, 3000]
    scen_dict={'BS':'Conservative', 'AP':'Realistic', 'NZ':'Optimistic'}

    fig, ax = plt.subplots(5, len(summary.year.unique()), figsize=(12, 10))

    keys_list = list(ex_quantities.keys())

    exp_h2_dict = {}

    for year, quantities in ex_quantities.items():
        position_x =  keys_list.index(year)
        for (idx,q) in enumerate(quantities):
            position_y = quantities.index(q)
            n = ns[year][scenario][q]

            links = n.links
            links_t = n.links_t

            exp_h2_links = n.links.loc[links.bus1 == 'H2 export bus']
            exp_h2_links_ts = links_t.p0[exp_h2_links.index] * n.snapshot_weightings.iloc[0,0] / 1e3
            exp_h2_links_ts = exp_h2_links_ts.resample(sample_rate).sum()      # .sum() .mean()

            exp_h2_dict['{} {} {} TWh'.format(year, scen_dict[scenario], q)] = exp_h2_links_ts

            #exp_h2_links_ts.rename(columns=ports, inplace=True)

            if len(summary.year.unique()) > 1:
                exp_h2_links_ts.plot(ax=ax[position_y, position_x])

                # Set the title
                ax[position_y, position_x].set_title('{} {} {} TWh'.format(year, scen_dict[scenario], q))
                ax[position_y, position_x].legend(bbox_to_anchor=(1, 2))
                if idx > 0:
                    ax[position_y, position_x].legend().set_visible(False)  # Hide the legend for the first subplot
                ax[position_y, position_x].set_xlabel('')  # Hide the x-label
            else:
                exp_h2_links_ts.plot(ax=ax[position_y])

                # Set the title
                ax[position_y].set_title('{} {} {} TWh'.format(year, scen_dict[scenario], q))
                # ax[position_y].legend(bbox_to_anchor=(1, 2))
                if idx > 0:
                    ax[position_y].legend().set_visible(False)  # Hide the legend for the first subplot
                ax[position_y].set_xlabel('')  # Hide the x-label 

    if len(summary.year.unique()) > 1:
        handles, labels = ax[position_y, position_x].get_legend_handles_labels()
    else:
        handles, labels = ax[position_y].get_legend_handles_labels()
    fig.legend(handles, labels, bbox_to_anchor=(0.8, 0.95), ncol=4)

    # Modify the legend labels
    # new_labels = ['Pecem (BR.6)', 'Aratu (BR.5)', 'Itaguai (BR.19)', 'Rio Grande (BR.21)']
    # new_labels = exp_h2_links_ts.columns.to_list()
    # fig.legend(new_labels, bbox_to_anchor=(0.8, 0.95), ncol=4)


    # Set the y-label for the whole figure
    fig.text(0.05, 0.5, 'Hydrogen delivery to export locations with weekly resampling [GWh]', va='center', rotation='vertical', fontdict={'fontsize': 14})


    # Adjust the spacing between subplots
    plt.subplots_adjust(wspace=0.3)  # Adjust the width spacing between subplots
    plt.subplots_adjust(hspace=0.6)  # Adjust the height spacing between subplots

    # plt.savefig('../outputs/Hydrogen_delivery_{}.png'.format(scen_dict[s]), bbox_inches='tight')
    #plt.savefig('../outputs_{}/Hydrogen_delivery_{}.png'.format(run[2050], scen_dict[s]), bbox_inches='tight')
    return(None)

def plot_geothermal_sh(df, run_name):
    delivery_schedule = run_name.split('_')[2]
    fig, ax = plt.subplots(1, 1)
    fig.set_size_inches(8, 6)
    df = df.filter(regex='geoth')
    df = df.rename(lambda c: c.split('_')[0], axis=1)
    # colors={
    #         'solar':'gold',
    #         'onwind':'blue',
    #         'onwind2':'royalblue',
    #         'offwind':'lightblue',
    #         'offwind2':'dodgerblue',
    #         'roof':'orange',
    #         'csp':'coral'
    #     }
    df.plot.bar(stacked=False, ax=ax, zorder=5) #, color=df.columns.map(colors)
    ax.set_ylabel('Expanded share of geothermal capacityin [%]')
    plt.suptitle('Expanded share of geothermal capacity | All scenarios | {}'.format(delivery_schedule), x=0.5, y=0.94, ha='center')
    fig.savefig(os.getcwd() + '/pypsa-earth-sec/outputs/{}/plots/geothermal_sh.png'.format(run_name), dpi=300, bbox_inches='tight')
    plt.close()

def plot_H2_pip_exp(df, run_name):
    delivery_schedule = run_name.split('_')[2]
    fig, ax = plt.subplots(1, 1)
    fig.set_size_inches(8, 6)
    df = df.filter(regex='pipeline')
    # df = df.rename(lambda c: c.split('_')[0], axis=1)
    prefix = 'H2_'
    df = df.rename(lambda c: f'{prefix}{c.split("_")[0]}', axis=1)
    # colors={
    #         'H2_pipeline':'dodgerblue',
    #     }
    df.plot.bar(stacked=False, ax=ax, zorder=5) # , color=df.columns.map(colors) 
    ax.set_ylabel('Hydrogen pipeline expansion capacity in [GWKm]')
    plt.suptitle('Hydrogen pipeline expansion capacity | All scenarios | {}'.format(delivery_schedule), x=0.5, y=0.94, ha='center')
    fig.savefig(os.getcwd() + '/pypsa-earth-sec/outputs/{}/plots/h2_pipe_caps.png'.format(run_name), dpi=300, bbox_inches='tight')
    plt.close()

def plot_pip_exp(df, run_name):
    carrier = run_name.split('_')[3].upper()
    fig, ax = plt.subplots(1, 1)
    fig.set_size_inches(8, 6)
    df = df.filter(regex='pipeline')
    df = df.rename(lambda c: f'{c.split("_")[0]}', axis=1)
    df.columns = df.columns.map(str.upper)
    df = df.droplevel('export_profile')
    df = df/1e3

    df.plot.bar(stacked=False, ax=ax, zorder=5) # , color=df.columns.map(colors) 

    # Remove vertical grid lines
    ax.yaxis.grid(True)  # Enable horizontal grid lines
    ax.xaxis.grid(False)  # Disable vertical grid lines

    ax.set_ylabel('Pipelines expansion capacity in [GWKm]')
    plt.suptitle('Pipelines expansion capacity | All scenarios | Shipping {}'.format(carrier), x=0.5, y=0.94, ha='center')
    fig.savefig(os.getcwd() + '/pypsa-earth-sec/outputs/{}/plots/pipe_expansion.png'.format(run_name), dpi=300, bbox_inches='tight')
    plt.close()

def plot_h2_export_prices(ns, summary, sample_rate='W', scenario='AP'):
    summary = summary.reset_index()
    summary = summary.loc[summary.export_quantity > 0]
    ex_quantities={2030: list(summary.loc[summary.year ==2030, 'export_quantity'].unique()),
                    2050: list(summary.loc[summary.year ==2050, 'export_quantity'].unique())} # , 2050: [10, 100, 500, 1000, 3000]
    scen_dict={'BS':'Conservative', 'AP':'Realistic', 'NZ':'Optimistic'}

    fig, ax = plt.subplots(5, len(summary.year.unique()), figsize=(12, 10))

    keys_list = list(ex_quantities.keys())

    exp_h2_dict = {}

    for year, quantities in ex_quantities.items():
        position_x =  keys_list.index(year)
        for (idx,q) in enumerate(quantities):
            position_y = quantities.index(q)
            n = ns[year][scenario][q]

            ex_buses = n.links.loc[n.links.bus1 == 'H2 export bus'].bus0
            mp_exp_ports = n.buses_t.marginal_price[ex_buses]
            mp_exp_bus = n.buses_t.marginal_price.filter(like='export')
            ex_prices = pd.concat([mp_exp_ports, mp_exp_bus], axis=1)
            ex_prices = ex_prices.resample('D').mean()
            
            # links = n.links
            # links_t = n.links_t

            # exp_h2_links = n.links.loc[links.bus1 == 'H2 export bus']
            # exp_h2_links_ts = links_t.p0[exp_h2_links.index] * n.snapshot_weightings.iloc[0,0] / 1e3
            # exp_h2_links_ts = exp_h2_links_ts.resample(sample_rate).sum()      # .sum() .mean()

            exp_h2_dict['{} {} {} TWh'.format(year, scen_dict[scenario], q)] = ex_prices

            #exp_h2_links_ts.rename(columns=ports, inplace=True)

            if len(summary.year.unique()) > 1:
                ex_prices.plot(ax=ax[position_y, position_x], linewidth=0.8)

                # Set the title
                ax[position_y, position_x].set_title('{} {} {} TWh'.format(year, scen_dict[scenario], q))
                ax[position_y, position_x].legend(bbox_to_anchor=(1, 2))
                if idx > 0:
                    ax[position_y, position_x].legend(bbox_to_anchor=(1,0.5)).set_visible(False)  # Hide the legend for the first subplot
                ax[position_y, position_x].set_xlabel('')  # Hide the x-label
            else:
                ex_prices.plot(ax=ax[position_y], linewidth=0.8)

                # Set the title
                ax[position_y].set_title('{} {} {} TWh'.format(year, scen_dict[scenario], q))
                # ax[position_y].legend(bbox_to_anchor=(1, 2))
                if idx > 0:
                    ax[position_y].legend().set_visible(False)  # Hide the legend for the first subplot
                ax[position_y].set_xlabel('')  # Hide the x-label 

    if len(summary.year.unique()) > 1:
        handles, labels = ax[position_y, position_x].get_legend_handles_labels()
    else:
        handles, labels = ax[position_y].get_legend_handles_labels()
    fig.legend(handles, labels, bbox_to_anchor=(0.8, 1), ncol=5)

    # Modify the legend labels
    # new_labels = ['Pecem (BR.6)', 'Aratu (BR.5)', 'Itaguai (BR.19)', 'Rio Grande (BR.21)']
    # new_labels = exp_h2_links_ts.columns.to_list()
    # fig.legend(new_labels, bbox_to_anchor=(0.8, 0.95), ncol=4)

    # Set the y-label for the whole figure
    fig.text(0.05, 0.5, 'Hydrogen prices at export locations and at artificial export bus with weekly resampling [€/MWh]', va='center', rotation='vertical', fontdict={'fontsize': 14})

    # Adjust the spacing between subplots
    plt.subplots_adjust(wspace=0.3)  # Adjust the width spacing between subplots
    plt.subplots_adjust(hspace=0.6)  # Adjust the height spacing between subplots

    # plt.savefig('../outputs/Hydrogen_delivery_{}.png'.format(scen_dict[s]), bbox_inches='tight')
    #plt.savefig('../outputs_{}/Hydrogen_delivery_{}.png'.format(run[2050], scen_dict[s]), bbox_inches='tight')
    return(None)
def make_legend_circles_for(sizes, scale=1.0, **kw):
    return [Circle((0, 0), radius=(s / scale) ** 0.5, **kw) for s in sizes]
def make_handler_map_to_scale_circles_as_in(ax, dont_resize_actively=False):
    fig = ax.get_figure()

    def axes2pt():
        return np.diff(ax.transData.transform([(0, 0), (1, 1)]), axis=0)[0] * (
            72.0 / fig.dpi
        )

    ellipses = []
    if not dont_resize_actively:

        def update_width_height(event):
            dist = axes2pt()
            for e, radius in ellipses:
                e.width, e.height = 2.0 * radius * dist

        fig.canvas.mpl_connect("resize_event", update_width_height)
        ax.callbacks.connect("xlim_changed", update_width_height)
        ax.callbacks.connect("ylim_changed", update_width_height)

    def legend_circle_handler(
        legend, orig_handle, xdescent, ydescent, width, height, fontsize
    ):
        w, h = 2.0 * orig_handle.get_radius() * axes2pt()
        e = Ellipse(
            xy=(0.5 * width - 0.5 * xdescent, 0.5 * height - 0.5 * ydescent),
            width=w,
            height=w,
        )
        ellipses.append((e, orig_handle.get_radius()))
        return e

    return {Circle: HandlerPatch(patch_func=legend_circle_handler)}

def plot_h2_infra(network):

    fig, ax = plt.subplots(subplot_kw={"projection": ccrs.Mercator()})

    fig.set_size_inches(10.5, 9)
    ex_qs = [network.links_t.p0.filter(like='export').sum().sum()/1e6*network.snapshot_weightings.iloc[0,0]]

    link_colors = ['blueviolet', 'mediumspringgreen', 'yellow',  'blue', 'cyan', 'red']

    for i, q in enumerate(ex_qs):

    # assign_location(n)
        n = network#s[2050]['AP'][q]
        if q > 200:
            bus_size_factor = 1e10#1e10
            linewidth_factor = 1e4
            elec_leg = 50
            pip_leg = 20
        else:
            bus_size_factor = 1e9#1e10
            linewidth_factor = 1e2
            elec_leg = 5
            pip_leg = 1
        # MW below which not drawn
        line_lower_threshold = 1e2
        bus_color = 'm'
        link_color = 'c'

        n.links.loc[:, "p_nom_opt"] = n.links.loc[:, "p_nom_opt"]
        # n.links.loc[n.links.carrier == "H2 Electrolysis"].p_nom_opt

        # Drop non-electric buses so they don't clutter the plot
        n.buses.drop(n.buses.index[n.buses.carrier != "AC"], inplace=True)

        elec = n.links.index[n.links.carrier == "H2 Electrolysis"]

        bus_sizes = (
            n.links.loc[elec, "p_nom_opt"].groupby(n.links.loc[elec, "bus0"]).sum()
            / bus_size_factor
        )

        # make a fake MultiIndex so that area is correct for legend
        bus_sizes.index = pd.MultiIndex.from_product([bus_sizes.index, ["electrolysis"]])

        n.links = n.links.filter(like='H2 pipeline', axis=0)

        #n.links.drop(n.links.index[n.links.carrier != "H2 pipeline"], inplace=True)

        link_widths = n.links.p_nom_opt / linewidth_factor
        link_widths[n.links.p_nom_opt < line_lower_threshold] = 0.0

        n.links.bus0 = n.links.bus0.str.replace(" H2", "")
        n.links.bus1 = n.links.bus1.str.replace(" H2", "")

        print(link_widths.sort_values())

        print(n.links[["bus0", "bus1"]])

        n_buses = n.buses
        n_buses = n_buses.loc[n_buses.carrier == 'AC']
        pos = n_buses[['x', 'y']].describe()
        span_x = pos.loc['max', 'x'] - pos.loc['min', 'x']
        span_y = pos.loc['max', 'y'] - pos.loc['min', 'y']
        
        #link_color = [float(q)]*len(n.links)
        n.plot(
            bus_sizes=bus_sizes*1e5,
            bus_colors={"electrolysis": bus_color},
            link_colors=link_color,
            link_widths=link_widths,
            branch_components=["Link"],
            color_geomap={"ocean": "lightblue", "land": "gainsboro"},
            ax=ax,
            boundaries=(pos.loc['min', 'x'] - span_x*0.15, pos.loc['max', 'x'] + span_x*0.15, pos.loc['min', 'y'] - span_y*0.15, pos.loc['max', 'y'] + span_y*0.15),
            #boundaries=(-75, -33, -35, 6), # Brazil
            #boundaries=(11, 26, -29, -15), # Namibia
            #boundaries=(21, 41, 42, 55), # Ukraine
            link_cmap='Dark2',
            #color_geomap='no_export'
        )


        handles = make_legend_circles_for(
            [elec_leg*1e9, 0.2*elec_leg*1e9], scale=bus_size_factor/1e9, facecolor=bus_color
        )
        labels = ["{} GW".format(s) for s in (elec_leg, int(0.2*elec_leg))]
        l2 = ax.legend(
            handles,
            labels,
            loc="lower right",
            #bbox_to_anchor=(0.01, 1.01),
            labelspacing=0.8,
            framealpha=1.0,
            title="Electrolyzer capacity",
            handler_map=make_handler_map_to_scale_circles_as_in(ax, dont_resize_actively=False),
        )
        ax.add_artist(l2)

        handles2 = []
        labels = []

        for s in (pip_leg, int(0.1*pip_leg)):
            handles2.append(
                plt.Line2D([0], [0], color=link_color, linewidth=s * 1e3 / linewidth_factor)#*1e3
            )
            labels.append("{} GW".format(s))
        l1_1 = ax.legend(
            handles2,
            labels,
            loc="upper right",
            #bbox_to_anchor=(0.32, 1.01),
            framealpha=1,
            labelspacing=0.8,
            handletextpad=1.5,
            title="H2 pipeline capacity",
        )
        ax.add_artist(l1_1)

def plot_res_caps(df, run_name):
    delivery_schedule = run_name.split('_')[2]
    fig, ax = plt.subplots(1, 1)
    fig.set_size_inches(8, 6)
    df = df.filter(regex='cap$').drop(df.filter(regex='_AC').columns, axis=1).drop('battery_cap', axis=1)
    df = df.rename(lambda c: c.split('_')[0], axis=1)
    colors={
            'solar':'gold',
            'onwind':'blue',
            'onwind2':'royalblue',
            'offwind':'lightblue',
            'offwind2':'dodgerblue',
            'roof':'orange',
            'csp':'coral'
        }
    df.plot.bar(stacked=True, ax=ax, color=df.columns.map(colors), zorder=5)
    ax.set_ylabel('RES installed capacity in [MW]')
    plt.suptitle('RES installed capacity | All scenarios | {}'.format(delivery_schedule), x=0.5, y=0.94, ha='center')
    fig.savefig(os.getcwd() + '/pypsa-earth-sec/outputs/{}/plots/res_caps.png'.format(run_name), dpi=300, bbox_inches='tight')
    plt.close()

def plot_res_caps_expansion(df, run_name):
    delivery_schedule = run_name.split('_')[2]
    fig, ax = plt.subplots(1, 1)
    fig.set_size_inches(8, 6)
    df = df.filter(regex='cap_expansion$')
    df = df.rename(lambda c: c.split('_')[0], axis=1)
    colors={
            'solar':'gold',
            'onwind':'blue',
            'onwind2':'royalblue',
            'offwind':'lightblue',
            'offwind2':'dodgerblue',
            'roof':'orange',
            'csp':'coral'
        }
    df.plot.bar(stacked=True, ax=ax, color=df.columns.map(colors), zorder=5)
    ax.set_ylabel('RES capacity expansion in [MW]')
    plt.suptitle('RES capacity expansion | All scenarios | {}'.format(delivery_schedule), x=0.5, y=0.94, ha='center')
    fig.savefig(os.getcwd() + '/pypsa-earth-sec/outputs/{}/plots/res_caps_expansion.png'.format(run_name), dpi=300, bbox_inches='tight')
    plt.close()

def plot_res_caps_exp_nodes(df, run_name, technology='solar'):
    delivery_schedule = run_name.split('_')[2]
    fig, ax = plt.subplots(1,3)
    fig.set_size_inches(20, 6)
    for (i_s, s) in enumerate(df.index.get_level_values(1).unique()):
        df_s = df.reset_index()
        df_s = df_s.loc[df_s.scenario == s].set_index(['scenario', 'export_quantity'])
        df_s_exp = df_s.filter(regex='cap$').filter(regex='_AC')
        #.filter(regex=technology)
        df_s_exp = df_s_exp.rename(lambda c: c.split(' ')[3], axis=1)
        df_s_exp = df_s_exp.T.groupby(df_s_exp.T.index).sum().T
        colors={
            'solar':'gold',
            'onwind':'blue',
            'onwind2':'royalblue',
            'offwind':'lightblue',
            'offwind2':'dodgerblue',
            'rooftop-solar':'orange',
            'csp':'coral'
        }
        if i_s > 0:
            df_s_exp.plot.bar(stacked=True, ax=ax[i_s], color=df_s_exp.columns.map(colors), zorder=5)
        else:
            df_s_exp.plot.bar(stacked=True, ax=ax[i_s], color=df_s_exp.columns.map(colors), zorder=5)
        ax[i_s].set_ylabel('RES expansion capacity at export nodes in [MW]')
    plt.suptitle('RES expansion capacity at export nodes | All scenarios | {}'.format(delivery_schedule), x=0.5, y=0.94, ha='center')
    fig.savefig(os.getcwd() + '/pypsa-earth-sec/outputs/{}/plots/res_caps_exp_nodes.png'.format(run_name), dpi=300, bbox_inches='tight')
    plt.close()

def plot_uhs_caps(ns, run_name):
    delivery_schedule = run_name.split('_')[2]
    df = pd.DataFrame()
    for y in ns.keys():
        fig, ax = plt.subplots(1, 1)
        fig.set_size_inches(8, 6)
        ns_y = ns[y]
        for (j, s) in enumerate(ns_y.keys()):
            ns_y_s = ns_y[s]
            for (i, q) in enumerate(ns_y_s.keys()):
                n = ns_y_s[q]
                n_uhs = n.stores.filter(like='H2 UHS', axis=0)
                n_uhs = n_uhs[n_uhs.e_nom_opt > 0].e_nom_opt.to_frame().T
                n_uhs.index = [i]

                df_n = pd.DataFrame(data={'scenario':s, 'export_quantity':q}, index=[i])
                df_n = pd.concat([df_n, n_uhs], axis=1)
                df = pd.concat([df, df_n])


    df.set_index(['scenario', 'export_quantity']).plot.bar(stacked=True, ax=ax, cmap=custom_cmap(), legend=True, zorder=5)
    ax.set_ylabel('Hydrogen storage capacity in MWh')
    plt.legend(bbox_to_anchor=(0.01, 1.25), loc='upper left', borderaxespad=0, ncol=3)
    plt.suptitle('Hydrogen storage capacity | All scenarios | {}'.format(delivery_schedule), x=0.5, y=1.18, ha='center')
    fig.savefig(os.getcwd() + '/pypsa-earth-sec/outputs/{}/plots/uhs_caps.png'.format(run_name), dpi=300, bbox_inches='tight')
    plt.close()


def plot_uhs_usage(ns, run_name):
    delivery_schedule = run_name.split('_')[2]
    df = pd.DataFrame()
    for y in ns.keys():
        ns_y = ns[y]
        for (j, s) in enumerate(ns_y.keys()):
            ns_y_s = ns_y[s]
            for (i, q) in enumerate(ns_y_s.keys()):
                n = ns_y_s[q]
                n_uhs = n.stores.filter(like='H2 UHS', axis=0)
                n_uhs = n_uhs[n_uhs.e_nom_opt > 0].e_nom_opt.to_frame().T
                n_uhs.index = [i]
                
                n_uhs_max = n.stores.filter(like='H2 UHS', axis=0)
                n_uhs_max = n_uhs_max[n_uhs_max.e_nom_max > 0].e_nom_max.to_frame().T
                n_uhs_max.index = [i]

                share_uhs = (n_uhs / n_uhs_max)*100

                df_n = pd.DataFrame(data={'scenario':s, 'export_quantity':q}, index=[i])
                df_n = pd.concat([df_n, share_uhs], axis=1)
                df = pd.concat([df, df_n])


    # Create subplots for each row
    fig, axs = plt.subplots(len(list(df.scenario.unique())), 1, figsize=(12, 7), sharex=False)

    # Ensure axs is a list even if there's only one subplot
    if not isinstance(axs, np.ndarray):
        axs = [axs]

    for i, scen in enumerate(list(df.scenario.unique())):
        df_scen = df[df.scenario == scen]
        df_scen.set_index(['scenario', 'export_quantity']).plot.bar(stacked=False, ax=axs[i], cmap=custom_cmap(), legend=False, zorder=5)
        # Make x-labels horizontal
        axs[i].set_xticklabels(axs[i].get_xticklabels(), rotation=0)
        

    plt.legend(bbox_to_anchor=(0.05, 4), loc='upper left', borderaxespad=0, ncol=4)  
    # plt.tight_layout()

    # Set the y-label for the whole figure
    fig.text(0.07, 0.5, 'Share of underground hydrogen storage usage [%]', va='center', rotation='vertical', fontdict={'fontsize': 13})
    plt.suptitle('Share of underground hydrogen storage | All scenarios | {}'.format(delivery_schedule), x=0.5, y=1.13, ha='center')
    fig.savefig(os.getcwd() + '/pypsa-earth-sec/outputs/{}/plots/uhs_usage.png'.format(run_name), dpi=300, bbox_inches='tight')
    plt.close()
            
def plot_elec_mix(df, run_name):
    delivery_schedule = run_name.split('_')[2]
    df = df.reset_index()
    fig, ax = plt.subplots(1,3)
    fig.set_size_inches(20, 6)

    #demand = df.loc[df.scenario == s].set_index(['year', 'scenario', 'export_quantity']).ac_demand
    for (idx_s,s) in enumerate(df.scenario.unique()):
        df_s = df.loc[df.scenario == s].set_index(['year', 'scenario', 'export_quantity'])[['electricity_mix_rel']]
        df_s_tech = df_s.electricity_mix_rel.apply(lambda m: pd.Series(m.split('\n')[1:]).apply(lambda s: s.split(' ')[0]))
        df_s_shares = df_s.electricity_mix_rel.apply(lambda m: pd.Series(m.split('\n')[1:]).apply(lambda s: float(s.split(' ')[-1])*100))
        df_s_shares.columns = df_s_tech.iloc[0].values
        # df_s_shares = df_s_shares[df_s_shares > 0.5].dropna(axis=1)
        # df_s_shares = df_s_shares[df_s_shares > 0.000001].dropna(axis=1)
        df_s_shares = df_s_shares.T.sort_values(by=(df_s_shares.index.get_level_values(0)[0], s, 0), ascending=False).T

        # #df_s_key = pd.Series(summary_res.electricity_mix_rel.iloc[0].split('\n')).apply(lambda s: s.split(' ')[0])
        # df_s_value = pd.Series(summary_res.electricity_mix_rel.iloc[0].split('\n')).apply(lambda s: s.split(' ')[-1])
        # df_s_value = df_s_value.iloc[1:].astype(float)
        # df_s_value.index = df_s_key.iloc[1:].values
        #mix_s = pd.DataFrame(index=df_s.index, data=df_s_value.to_dict())
        #mix_s = mix_s * demand
        colors={
            'solar':'gold',
            'onwind':'steelblue',
            'onwind2':'royalblue',
            'offwind':'lightblue',
            'offwind2':'cyan',
            'rooftop-solar':'orange',
            'csp':'coral',
            'biomass':'green',
            'hydro':'midnightblue',
            'ror':'slateblue',
            'nuclear':'greenyellow',
            'coal':'brown',
            'OCGT':'red',
            'CCGT':'darkred',
            'oil':'grey',
            'lignite':'black',
            'gas_CHP':'crimson',
            'biomass_CHP':'lawngreen',
            'geothermal': '#ba91b1',
            'offwind-ac': 'lightblue',
            'offwind-dc': 'lightblue',
        }
        
        df_s_shares.plot.bar(stacked=True, ax=ax[idx_s], color=df_s_shares.columns.map(colors), zorder=5)
    
        ax[idx_s].set_ylabel('Electricity share [%]')
        
        h, l = ax[idx_s].get_legend_handles_labels()
        #ax[idx_s].legend(bbox_to_anchor=(0.6,1.3), ncol=3, handles=h[:int(len(h)/3)], labels=l[:int(len(l)/3)])
        ax[idx_s].legend(bbox_to_anchor=(1,1.3), ncol=3, handles=h, labels=l)
    plt.suptitle('Electricity mix | All scenarios | {}'.format(delivery_schedule), x=0.5, y=1.19, ha='center')
    fig.savefig(os.getcwd() + '/pypsa-earth-sec/outputs/{}/plots/electricity_mix.png'.format(run_name), dpi=300, bbox_inches='tight')
    plt.close()





def plot_energy_mix(df, run_name):
    delivery_schedule = run_name.split('_')[2]
    df = df.copy()
    df = df.reset_index()
    fig, ax = plt.subplots(1,3)
    fig.set_size_inches(20, 6)

    #demand = df.loc[df.scenario == s].set_index(['year', 'scenario', 'export_quantity']).ac_demand
    for (idx_s,s) in enumerate(df.scenario.unique()):
        df_s = df.loc[df.scenario == s].set_index(['year', 'scenario', 'export_quantity'])[['energy_mix_abs']]
        df_s_tech = df_s.energy_mix_abs.apply(lambda m: pd.Series(m.split('\n')[1:]).apply(lambda s: s.split('   ')[0]))
        df_s_shares = df_s.energy_mix_abs.apply(lambda m: pd.Series(m.split('\n')[1:]).apply(lambda s: float(s.split('   ')[-1])))
        df_s_shares.columns = df_s_tech.iloc[0].values
        # df_s_shares = df_s_shares[df_s_shares > 0.5].dropna(axis=1)
        # df_s_shares.columns = df_s_shares.columns[df_s_shares.iloc[-1].argsort()]
        df_s_shares = df_s_shares[df_s_shares > 0.02].dropna(axis=1)
        df_s_shares = df_s_shares.T.sort_values(by=(df_s_shares.index.get_level_values(0)[0], s, 0), ascending=False).T

        # #df_s_key = pd.Series(summary_res.electricity_mix_rel.iloc[0].split('\n')).apply(lambda s: s.split(' ')[0])
        # df_s_value = pd.Series(summary_res.electricity_mix_rel.iloc[0].split('\n')).apply(lambda s: s.split(' ')[-1])
        # df_s_value = df_s_value.iloc[1:].astype(float)
        # df_s_value.index = df_s_key.iloc[1:].values
        #mix_s = pd.DataFrame(index=df_s.index, data=df_s_value.to_dict())
        #mix_s = mix_s * demand
        colors={
            'solar':'gold',
            'onwind':'steelblue',
            'onwind2':'royalblue',
            'offwind':'lightblue',
            'offwind2':'cyan',
            'rooftop-solar':'orange',
            'csp':'coral',
            'solar thermal':'lightcoral',
            'biomass':'green',
            'solid biomass':'green',
            'hydro':'midnightblue',
            'ror':'slateblue',
            'nuclear':'greenyellow',
            'coal':'brown',
            'OCGT':'red',
            'CCGT':'darkred',
            'oil':'grey',
            'biogas':'lawngreen',
            'gas':'crimson',
            'lignite':'black',
            'geothermal': '#ba91b1',
            'urban central solar thermal':'coral',
            'PHS': '#00008B',
        }
        
        df_s_shares.plot.bar(stacked=True, ax=ax[idx_s], color=df_s_shares.columns.map(colors), zorder=5)

        ax[idx_s].set_ylabel('Energy share [MWh]')
        
        h, l = ax[idx_s].get_legend_handles_labels()
        #ax[idx_s].legend(bbox_to_anchor=(0.6,1.3), ncol=3, handles=h[:int(len(h)/3)], labels=l[:int(len(l)/3)])
        ax[idx_s].legend(bbox_to_anchor=(1,1.3), ncol=3, handles=h, labels=l)
    plt.suptitle('Energy mix | All scenarios | {}'.format(delivery_schedule), x=0.5, y=1.19, ha='center')
    fig.savefig(os.getcwd() + '/pypsa-earth-sec/outputs/{}/plots/energy_mix.png'.format(run_name), dpi=300, bbox_inches='tight')
    plt.close()

def plot_mps(df, run_name):
    df = df.reset_index()

    plt.rcParams.update({
        "text.usetex": True,
        "font.family": "Helvetica"
    })
    plt.rc('text.latex', preamble=r'\usepackage{cmbright}')
    fig, axs = plt.subplots(len(df.year.unique()), 1)
    fig.set_size_inches(12, 4*len(df.year.unique()))

    color_dict = {'elec': '#005b7f', 'h2':'#b2d235', 'NZ':'#b2d235'}
    marker_dict = {'BS': '^', 'AP':'s', 'NZ':'o'}
    scen_dict = {'BS': 'Conservative', 'AP':'Realistic', 'NZ':'Optimistic'}

    for i, y in enumerate(df.year.unique()):
        
        if len(df.year.unique()) > 1:
            ax = axs[i]
        else:
            ax = axs
        df_y = df.loc[df.year == y]
        if (y == 2050):
            df_y = df_y.loc[df_y.export_quantity <= 3000]

        
        min_elec = df_y[['export_quantity', 'elec_wap']].groupby('export_quantity', as_index=False).min(numeric_only=True)
        max_elec = df_y[['export_quantity', 'elec_wap']].groupby('export_quantity', as_index=False).max(numeric_only=True)

        min_h2 = df_y[['export_quantity', 'h2_wap']].groupby('export_quantity').min(numeric_only=True)/33.3*1e3
        max_h2 = df_y[['export_quantity', 'h2_wap']].groupby('export_quantity').max(numeric_only=True)/33.3*1e3

        plots1 = []
        plots2 = []
        for s in df_y.scenario.unique():
            df_y_s = df_y.loc[df_y.scenario == s]
            df_y_s = df_y_s.set_index('export_quantity')
            ax.scatter(df_y_s.index, df_y_s.elec_wap, label=scen_dict[s], color=color_dict['elec'], marker=marker_dict[s])#, linestyle='dashed', linewidth=0.8)
            ax.scatter(df_y_s.index, df_y_s.h2_wap/33.3*1e3, label=scen_dict[s], color=color_dict['h2'], marker=marker_dict[s])#, linestyle='dashed', linewidth=0.8)


            ax.fill_between(min_elec.export_quantity, min_elec.elec_wap, max_elec.elec_wap, color=color_dict['elec'], alpha=.1)
            ax.fill_between(min_h2.index, min_h2.h2_wap, max_h2.h2_wap, color=color_dict['h2'], alpha=.1)
            ax.set_ylim((0, max(max_h2.h2_wap.max(), max_elec.elec_wap.max())))
            ax.tick_params(axis='both', which='major', labelsize=20)
            if (y == 2030):
                ax.set_xticklabels([])
                ax.legend(loc='upper left', fontsize=10, ncol=3)
                h, l = ax.get_legend_handles_labels()
                leg1 = ax.legend(handles=[i for i in h[0::2]], labels=[i for i in l[0::2]], loc='upper right', fontsize=18, title=r'\huge\textbf{Electricity}', bbox_to_anchor=(0.3, 1.6))
                ax.legend(handles=[i for i in h[1::2]], labels=[i for i in l[1::2]], loc='upper right', fontsize=18, title=r'\huge\textbf{Hydrogen}', bbox_to_anchor=(1, 1.6))
                ax.add_artist(leg1)
            else:
                ax.set_xlabel(r'\textbf{Export quantity [TWh]}', fontsize=20)

            ax.set_title(y, fontdict={'size':20})
            fig.text(0.05, 0.5, r'\textbf{Average prices [€/MWh]}', va='center', rotation='vertical', fontsize=20)
    fig.savefig(os.getcwd() + '/pypsa-earth-sec/outputs/{}/plots/market_prices.png'.format(run_name), dpi=300, bbox_inches='tight')







def flatten_dict(d, parent_key='', sep='_'):
    items = []
    for k, v in d.items():
        new_key = f'{parent_key}{sep}{k}' if parent_key else str(k)
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)


preferred_order = pd.Index(
    [
        "transmission lines",
        "hydroelectricity",
        "hydro reservoir",
        "run of river",
        "pumped hydro storage",
        "solid biomass",
        "biogas",
        "onshore wind",
        "offshore wind",
        "offshore wind (AC)",
        "offshore wind (DC)",
        "solar PV",
        "solar thermal",
        "solar",
        "building retrofitting",
        "ground heat pump",
        "air heat pump",
        "heat pump",
        "resistive heater",
        "power-to-heat",
        "gas-to-power/heat",
        "CHP",
        "OCGT",
        "gas boiler",
        "gas",
        "natural gas",
        "helmeth",
        "methanation",
        "hydrogen storage",
        "power-to-gas",
        "power-to-liquid",
        "battery storage",
        "hot water storage",
        "CO2 sequestration",
        "geothermnal"
    ]
)


def rename_techs(label):
    prefix_to_remove = [
        "residential ",
        "services ",
        "urban ",
        "rural ",
        "central ",
        "decentral ",
    ]

    rename_if_contains = [
        "CHP",
        "gas boiler",
        "biogas",
        " biogas",
        "solar thermal",
        "air heat pump",
        "ground heat pump",
        "resistive heater",
        " resistive heater",
        "Fischer-Tropsch",
        " Fischer-Tropsch",
    ]

    rename_if_contains_dict = {
        "water tanks": "hot water storage",
        "retrofitting": "building retrofitting",
        "H2": "hydrogen storage",
        "battery": "battery storage",
        "CCS": "CCS",
    }

    rename = {
        "solar": "solar PV",
        "Sabatier": "methanation",
        "offwind": "offshore wind",
        "offwind2": "offshore wind",
        "offwind-ac": "offshore wind (AC)",
        "offwind-dc": "offshore wind (DC)",
        "onwind": "onshore wind",
        "onwind2": "onshore wind",
        "ror": "hydroelectricity",
        "hydro": "hydroelectricity",
        "PHS": "hydroelectricity",
        "co2 Store": "DAC",
        "co2 stored": "CO2 sequestration",
        "AC": "transmission lines",
        "DC": "transmission lines",
        "B2B": "transmission lines",
    }


    for ptr in prefix_to_remove:
        if label[: len(ptr)] == ptr:
            label = label[len(ptr) :]

    for rif in rename_if_contains:
        if rif in label:
            label = rif

    for old, new in rename_if_contains_dict.items():
        if old in label:
            label = new

    for old, new in rename.items():
        if old == label:
            label = new
    return label

def rename_techs_tyndp(tech):
    if tech.startswith(" "):
        tech = tech.lstrip()

    tech = rename_techs(tech)
    if "heat pump" in tech or "resistive heater" in tech or "hot water storage" in tech:
        return "power-to-heat"
    elif tech in ["methanation", "hydrogen storage", "helmeth"]:
        return "power-to-gas"
    elif tech in ["OCGT", "CHP", "gas boiler"]:
        return "gas-to-power/heat"
    elif "solar" in tech:
        return "solar"
    elif tech == "Fischer-Tropsch":
        return "power-to-liquid"
    elif "offshore wind" in tech:
        return "offshore wind"
    elif "CCGT" in tech:
        return "gas-to-power/heat"
    elif "geothermal" in tech:
        return "geothermal"
    elif "N2" in tech:
        return "nitrogen"
    elif "NH3" in tech:
        return "ammonia"
    else:
        return tech

def assign_location(n):
    for c in n.iterate_components(n.one_port_components | n.branch_components):
        ifind = pd.Series(c.df.index.str.find(" ", start=4), c.df.index)

        for i in ifind.value_counts().index:
            # these have already been assigned defaults
            if i == -1:
                continue

            names = ifind.index[ifind == i]

            c.df.loc[names, "location"] = names.str[:i]

tech_colors={
  0: "pink", # black
  " oil Store": "#B5A642",
  "SMR CC": "darkblue",
  "csp": "gold",
  "gas for industry CC": "brown",
  "process emissions CC": "gray",
  "CO2 pipeline": "gray",
  "onwind": "dodgerblue",
  "onwind2": "dodgerblue",
  "onshore wind": "#235ebc",
  "offwind": "#6895dd",
  "offwind2": "#6895dd",
  "offshore wind": "#6895dd",
  "offwind-ac": "c",
  "offshore wind (AC)": "#6895dd",
  "offwind-dc": "#74c6f2",
  "offshore wind (DC)": "#74c6f2",
  "wave": '#004444',
  "hydro": '#3B5323',
  "hydro reservoir": '#3B5323',
  "ror": '#78AB46',
  "run of river": '#78AB46',
  "hydroelectricity": 'blue',
  "solar": "orange",
  "solar PV": "#f9d002",
  "solar thermal": "coral",
  "solar rooftop": '#ffef60',
  "OCGT": "wheat",
  "OCGT marginal": "sandybrown",
  "OCGT-heat": '#ee8340',
  "gas boiler": '#ee8340',
  "gas boilers": '#ee8340',
  "gas boiler marginal": '#ee8340',
  "gas-to-power/heat": 'brown',
  "gas": "brown",
  "natural gas": "brown",
  "SMR": '#4F4F2F',
  "oil": '#B5A642',
  "oil boiler": '#B5A677',
  "lines": "k",
  "transmission lines": "k",
  "H2": "m",
  "H2 liquefaction": "m",
  "hydrogen storage": "m",
  "battery": "#40E0D0",
  "battery storage": "#40E0D0",
  "home battery": '#614700',
  "home battery storage": '#614700',
  "Nuclear": "yellowgreen",
  "Nuclear marginal": "yellowgreen",
  "nuclear": "yellowgreen",
  "uranium": "y",
  "Coal": "k",
  "coal": "k",
  "Coal marginal": "k",
  "Lignite": "grey",
  "lignite": "grey",
  "Lignite marginal": "grey",
  "CCGT": '#ee8340',
  "CCGT marginal": '#ee8340',
  "heat pumps": '#76EE00',
  "heat pump": '#76EE00',
  "air heat pump": '#76EE00',
  "ground heat pump": '#40AA00',
  "power-to-heat": 'red',
  "resistive heater": "pink",
  "Sabatier": '#FF1493',
  "methanation": '#FF1493',
  "power-to-gas": 'purple',
  "electrolysis": 'purple',
  "power-to-liquid": 'olive',
  "helmeth": '#7D0552',
  "DAC": 'deeppink',
  "co2 stored": '#123456',
  "CO2 sequestration": '#123456',
  "CC": "k",
  "co2": '#123456',
  "co2 vent": '#654321',
  "agriculture heat": '#D07A7A',
  "agriculture machinery oil": '#1e1e1e',
  "agriculture machinery oil emissions": '#111111',
  "agriculture electricity": '#222222',
  "solid biomass for industry co2 from atmosphere": '#654321',
  "solid biomass for industry co2 to stored": '#654321',
  "solid biomass for industry CC": '#654321',
  "gas for industry co2 to atmosphere": '#654321',
  "gas for industry co2 to stored": '#654321',
  "Fischer-Tropsch": '#44DD33',
  "kerosene for aviation": '#44BB11',
  "naphtha for industry": '#44FF55',
  "land transport oil": '#44DD33',
  "water tanks": '#BBBBBB',
  "hot water storage": '#BBBBBB',
  "hot water charging": '#BBBBBB',
  "hot water discharging": '#999999',
  # CO2 pipeline: '#999999'
  "CHP": "r",
  "CHP heat": "r",
  "CHP electric": "r",
  "PHS": "g",
  "Ambient": "k",
  "Electric load": "b",
  "Heat load": "r",
  "heat": "darkred",
  "rural heat": '#880000',
  "central heat": '#b22222',
  "decentral heat": '#800000',
  "low-temperature heat for industry": '#991111',
  "process heat": '#FF3333',
  "heat demand": "darkred",
  "electric demand": "k",
  "Li ion": "grey",
  "district heating": '#CC4E5C',
  "retrofitting": "purple",
  "building retrofitting": "purple",
  "BEV charger": "grey",
  "V2G": "grey",
  "land transport EV": "grey",
  "electricity": "k",
  "gas for industry": '#333333',
  "solid biomass for industry": '#555555',
  "industry electricity": '#222222',
  "industry new electricity": '#222222',
  "process emissions to stored": '#444444',
  "process emissions to atmosphere": '#888888',
  "process emissions": '#222222',
  "oil emissions": '#666666',
  "industry oil emissions": '#666666',
  "land transport oil emissions": '#666666',
  "land transport fuel cell": '#AAAAAA',
  "biogas": '#800000',
  "solid biomass": '#DAA520',
  "today": '#D2691E',
  "shipping": '#6495ED',
  "shipping oil": "#6495ED",
  "shipping oil emissions": "#6495ED",
  "electricity distribution grid": 'y',
  "solid biomass transport": "green",
  "biomass EOP": "green",
  "H2 for industry": "#222222",
  "H2 for shipping": "#6495ED",
  "other": "grey",
  "biomass": "green",
  'CCS':'deeppink',
  'biomass transport':'darkseagreen',
  'process emissions':'brown',
  'transmission lines':'steelblue',
  'gas CC':'tomato',
  'biomass CC':'limegreen',
  'rail transport electricity':'grey',
  'AC':'steelblue',
  'agriculture oil':'#B5A642',
  'rail transport oil':'#B5A642',
  'residential biomass':'#DAA520',
  'residential oil':'#B5A642',
  'services oil':'#B5A642',
  'residential rural heat':'darkred',
  'services biomass':'#555555',
  'geothermal': '#ba91b1',
  'N2':'#46caf0',
  'nitrogen':'#46caf0',
  'NH3':'#008B8B',
  'ammonia':'#008B8B',
  'NH3 pipeline': '#FF8C00',
  'ammonia pipeline': '#FF8C00',
  }



def plot_export_shares_ports(ns, run_name):
    df = pd.DataFrame()

    for key in ns.keys():
        # Split the text by underscore and get the last element
        qty = key.split("_")[-1]

        # Find the index of the last and second-to-last underscores
        last_underscore_index = key.rfind("_")
        second_last_underscore_index = key.rfind("_", 0, last_underscore_index)

        # Extract the text between the last two underscores
        scenario = key[second_last_underscore_index + 1:last_underscore_index]

        # Find the index of the first and second underscores
        first_underscore_index = key.find("_")
        second_underscore_index = key.find("_", first_underscore_index + 1)

        # Extract the text between the first two underscores
        year = key[first_underscore_index + 1:second_underscore_index]

        if qty != '0':
            n = ns[key].copy()

            df0 = calc_export_shares_2(n, absolute=False)
            df0.index = df0.index.str.replace('_AC H2 export', '')

            df0 = df0.reset_index().rename(columns={'Link': 'Region', 0: '{} {} {} TWh'.format(year, scen_dict[scenario], qty)}).set_index('Region')
            df = pd.merge(df, df0['{} {} {} TWh'.format(year, scen_dict[scenario], qty)], left_index=True, right_index=True, how='outer')

            # Fill NaN values with zero
            df.fillna(0, inplace=True)

    annot_df = pd.DataFrame()

    for key in ns.keys():
        # Split the text by underscore and get the last element
        qty = key.split("_")[-1]

        # Find the index of the last and second-to-last underscores
        last_underscore_index = key.rfind("_")
        second_last_underscore_index = key.rfind("_", 0, last_underscore_index)

        # Extract the text between the last two underscores
        scenario = key[second_last_underscore_index + 1:last_underscore_index]

        # Find the index of the first and second underscores
        first_underscore_index = key.find("_")
        second_underscore_index = key.find("_", first_underscore_index + 1)

        # Extract the text between the first two underscores
        year = key[first_underscore_index + 1:second_underscore_index]

        if qty != '0':
            n = ns[key].copy()

            df0 = calc_export_shares_2(n, absolute=True)
            df0.index = df0.index.str.replace('_AC H2 export', '')
            
            df0 = df0.reset_index().rename(columns={'Link': 'Region', 0: '{} {} {} TWh'.format(year, scen_dict[scenario], qty)}).set_index('Region')
            # annot_df.index = df0.index
            # annot_df['{} {} {} TWh'.format(year, scen_dict[scenario], qty)] = df0['{} {} {} TWh'.format(year, scen_dict[scenario], qty)]
            annot_df = pd.merge(annot_df, df0['{} {} {} TWh'.format(year, scen_dict[scenario], qty)], left_index=True, right_index=True, how='outer')

            # Fill NaN values with zero
            annot_df.fillna(0, inplace=True)


    fig, ax = plt.subplots(1, 1)

    # Set the figure size
    fig.set_size_inches(8, 6) # 14, 11

    # Create a heatmap
    heatmap = sns.heatmap(df.T, cmap='Blues', ax=ax,  annot=annot_df.T.values, fmt=".2f") # viridis    (annot=True for values of df instead of annot_df)

    # Show all column labels

    # plt.yticks(range(len(df.columns)), df.columns)
    ax.set_yticks(np.arange(len(df.columns)) + 0.5, df.columns)

    # Calculate the extension length (1cm)
    extension_length = 0.01

    # Adjust the x-axis limits to extend the line outside the xlim
    x_start = ax.get_xlim()[0] - extension_length  # Subtract 1 from the x-axis lower limit
    x_end = ax.get_xlim()[1] + extension_length  # Add 1 to the x-axis upper limit

    # ax.hlines([5, 10, 15, 20, 25], x_start, x_end)
    ax.hlines([5, 10, 15, 20, 25], *ax.get_xlim(), color='indianred')
    ax.hlines([ 15], *ax.get_xlim(), color='indianred', linewidth=5)

    # plt.axhline(y=5, xmin=-1, xmax=25, color='red', zorder=1)

    # Add labels and title
    # plt.xlabel('Columns')
    # plt.ylabel('Rows')

    # Set the color bar title
    heatmap.collections[0].colorbar.set_label('Quantity share of hydrogen delivery per export location \n (Values are absolute quantities)')

    # plt.savefig('../outputs/Quantity_share_per_export_loc.png', transparent=True, bbox_inches="tight", dpi=300)
    plt.savefig(os.getcwd()+'/pypsa-earth-sec/outputs/{}/plots/Quantity_share_per_export_loc.png'.format(run_name), transparent=False, dpi=300, bbox_inches="tight") 

    plt.close()



    #------------------------------------------------------------------------
    #------------------------------------------------------------------------
    #------------------------------------------------------------------------
    #------------------------------------------------------------------------




def plot_map(
    network,
    key,
    boundaries,
    expansion,
    run_name,
    path_subregions,
    plot_map_factors,
    components=[
        "links",
        "generators",
        "stores",
        "storage_units"], #TODO uncomment after adding storage units
    bus_size_factor=1e10,

    transmission=False,
    geometry=True,

):
    # plot_labels_2030 = {
    #     "onshore wind": "",
    #     #"offshore wind": "c",
    #     #"hydroelectricity": "",
    #     "solar": "",    
    #     #"biomass": "y",
    #     "electrolysis": "",
    #     "hydrogen storage": "",
    #     "gas-to-power/heat": "orange",
    #     #"power-to-heat": "red",
    #     #"power-to-liquid": "",
    #     #"oil":"",
    #     #"nuclear": "",
    #     #"DAC": "",
    #     }

    # if run_name.split("_")[0] == "TR":
    #     plot_labels_2050 = {
    #         "onshore wind": "",
    #         #"offshore wind": "c",
    #         #"hydroelectricity": "",
    #         "solar": "",    
    #         "biomass": "",
    #         "electrolysis": "",
    #         "hydrogen storage": "",
    #         "gas-to-power/heat": "orange",
    #         #"power-to-heat": "",
    #         "power-to-liquid": "",
    #         "battery storage":"",
    #         #"nuclear": "",
    #         "DAC": "",
    #         "geothermal": "",
    #         }
    # else:
    #     plot_labels_2050 = {
    #     "onshore wind": "",
    #     #"offshore wind": "c",
    #     #"hydroelectricity": "",
    #     "solar": "",    
    #     "biomass": "",
    #     "electrolysis": "",
    #     "hydrogen storage": "",
    #     "gas-to-power/heat": "orange",
    #     #"power-to-heat": "",
    #     "power-to-liquid": "",
    #     "battery storage":"",
    #     #"nuclear": "",
    #     "DAC": "",
    #     # "geothermal": "",
    #     }




    print(run_name)
    n = network.copy()
    assign_location(n)
    # Drop non-electric buses so they don't clutter the plot
    n.buses.drop(n.buses.index[n.buses.carrier != "AC"], inplace=True)
    
    costs = pd.DataFrame(index=n.buses.index)

    for comp in components:
        df_c = getattr(n, comp)
        df_c["nice_group"] = df_c.carrier.map(rename_techs_tyndp)


        if expansion == True:
            if comp == "stores":
                attr = "e_nom_opt"
                attr_nom = "e_nom"
            else:
                attr = "p_nom_opt"
                attr_nom = "p_nom"
            #attr = "e_nom_opt" if comp == "stores" else "p_nom_opt"

            costs_c = (
                (df_c.capital_cost * df_c[attr] - df_c.capital_cost * df_c[attr_nom])
                .groupby([df_c.location, df_c.nice_group])
                .sum()
                .unstack()
                .fillna(0.0)
            )

        else:
        
            attr = "e_nom_opt" if comp == "stores" else "p_nom_opt"

            costs_c = (
                (df_c.capital_cost * df_c[attr])
                .groupby([df_c.location, df_c.nice_group])
                .sum()
                .unstack()
                .fillna(0.0)
            )

        costs = pd.concat([costs, costs_c], axis=1)

        #print(comp, costs)
    costs = costs.groupby(costs.columns, axis=1).sum()

    costs.drop(list(costs.columns[(costs == 0.0).all()]), axis=1, inplace=True)

    new_columns = preferred_order.intersection(costs.columns).append(
        costs.columns.difference(preferred_order)
    )
    costs = costs[new_columns]

    for item in new_columns:
        if item not in tech_colors:
            print("Warning!", item, "not in config/plotting/tech_colors")

    costs = costs.stack()  # .sort_index()

    n.links.drop(
        n.links.index[(n.links.carrier != "DC") & (n.links.carrier != "B2B")],
        inplace=True,
    )

    # drop non-bus
    to_drop = costs.index.levels[0].symmetric_difference(n.buses.index)
    if len(to_drop) != 0:
        print("dropping non-buses", list(to_drop))
        costs.drop(to_drop, level=0, inplace=True, axis=0)

    # make sure they are removed from index
    costs.index = pd.MultiIndex.from_tuples(costs.index.values)

    # PDF has minimum width, so set these to zero
    line_lower_threshold = 500.0
    line_upper_threshold = 1e4
    linewidth_factor = 2e3
    ac_color = "gray"
    dc_color = "m"

    # if snakemake.wildcards["lv"] == "1.0":         #TODO when we add wildcard lv
    # should be zero
    line_widths = n.lines.s_nom_opt - n.lines.s_nom
    link_widths = n.links.p_nom_opt - n.links.p_nom
    title = "Technologies"

    if transmission:
        line_widths = n.lines.s_nom_opt
        link_widths = n.links.p_nom_opt
        linewidth_factor = 2e3
        line_lower_threshold = 0.0
        title = "Technologies"
    else:
        line_widths = n.lines.s_nom_opt - n.lines.s_nom_min
        line_widths = (
            n.lines.s_nom_opt - n.lines.s_nom_opt
        )  # TODO when we add wildcard lv
        link_widths = n.links.p_nom_opt - n.links.p_nom_min
        title = "Transmission reinforcement"

        if transmission:
            line_widths = n.lines.s_nom_opt
            link_widths = n.links.p_nom_opt
            title = "Total transmission"

    line_widths.loc[line_widths < line_lower_threshold] = 0.0
    link_widths.loc[link_widths < line_lower_threshold] = 0.0

    line_widths.loc[line_widths > line_upper_threshold] = line_upper_threshold
    link_widths.loc[link_widths > line_upper_threshold] = line_upper_threshold


    # Step 1: Identify Index Level 1 values to remove
    # Here 'level=0' refers to nodes (index level 0), and 'level=1' refers to the technologies (index level 1)
    to_remove = costs.groupby(level=1).sum() <= 1000000

    # Step 2: Filter the DataFrame
    # Filter out the technologies (index level 1) where the condition is met
    costs = costs[~costs.index.get_level_values(1).isin(to_remove[to_remove].index)]

    # Step 3: Identify the displayed technologies
    displayed_technologies = costs.index.get_level_values(1).unique()

    # print(costs)

    # Step 4: Filter the color dictionary to only include these technologies
    filtered_color_dict = {tech: tech_colors[tech] for tech in displayed_technologies if tech in tech_colors}



    fig, ax = plt.subplots(subplot_kw={"projection": ccrs.PlateCarree()})
    fig.set_size_inches(10.5, 9)

    if int(key.split("_")[-1]) <=50 and int(key.split("_")[1]) == 2030 :
        bus_size_factor = plot_map_factors[run_name.split("_")[0]]['below_50_and_2030']['bus_size_factor']
        bigger_pie = plot_map_factors[run_name.split("_")[0]]['below_50_and_2030']['bigger_pie']
        smaller_pie = plot_map_factors[run_name.split("_")[0]]['below_50_and_2030']['smaller_pie']
    elif int(key.split("_")[-1]) <=50 and int(key.split("_")[1]) == 2050 :
        bus_size_factor = plot_map_factors[run_name.split("_")[0]]['below_50_and_2050']['bus_size_factor']
        bigger_pie = plot_map_factors[run_name.split("_")[0]]['below_50_and_2050']['bigger_pie']
        smaller_pie = plot_map_factors[run_name.split("_")[0]]['below_50_and_2050']['smaller_pie']

    elif (int(key.split("_")[-1]) <=1000) :
        bus_size_factor = plot_map_factors[run_name.split("_")[0]]['below_1000']['bus_size_factor']
        bigger_pie = plot_map_factors[run_name.split("_")[0]]['below_1000']['bigger_pie']
        smaller_pie = plot_map_factors[run_name.split("_")[0]]['below_1000']['smaller_pie']
    else:
        bus_size_factor = plot_map_factors[run_name.split("_")[0]]['other']['bus_size_factor']
        bigger_pie = plot_map_factors[run_name.split("_")[0]]['other']['bigger_pie']
        smaller_pie = plot_map_factors[run_name.split("_")[0]]['other']['smaller_pie']
        
    print(costs.unstack().columns)
    color_dict = tech_colors
    color_dict["H2 store"] = "lightcoral"
    color_dict["hydrogen storage"] = "lightcoral"
    color_dict["power-to-liquid"] = "darkslategray"
    n.plot(
        bus_sizes=costs / bus_size_factor,
        bus_colors=color_dict,
        line_colors=ac_color,
        link_colors=dc_color,
        line_widths=line_widths / linewidth_factor,
        link_widths=link_widths / linewidth_factor,
        ax=ax,
        boundaries=boundaries[run_name.split("_")[0]],
        geomap="10m",
        color_geomap={"ocean": "lightblue", "land": "gainsboro"},
    )

    handles = make_legend_circles_for(
        [bigger_pie, smaller_pie], scale=bus_size_factor, facecolor="gray"
    )
    labels = ["{} b€/a".format(s) for s in (bigger_pie/1e9, smaller_pie/1e9)]
    
    if run_name.split("_")[0] == "NA":
        l2 = ax.legend(
            handles,
            labels,
            loc="upper left",
            bbox_to_anchor=(0.72, 0.7),
            labelspacing=1.0,
            framealpha=1.0,
            title="System cost",
            title_fontsize=18,
            fontsize=18,
            handler_map=make_handler_map_to_scale_circles_as_in(ax),
        )
    else:
        l2 = ax.legend(
            handles,
            labels,
            loc="upper left",
            bbox_to_anchor=(0.72, 1.005),
            labelspacing=1.0,
            framealpha=1.0,
            title="System cost",
            title_fontsize=18,
            fontsize=18,
            handler_map=make_handler_map_to_scale_circles_as_in(ax),
        )
    ax.add_artist(l2)
    
    subregions = gpd.read_file(path_subregions)

    ax.add_geometries(subregions['geometry'], facecolor='oldlace', edgecolor='dimgrey', crs=ccrs.PlateCarree())
    handles = []
    labels = []

    for tech, color in filtered_color_dict.items():
        handles.append(plt.Line2D([0], [0], color=color, linewidth=15))
        labels.append(tech)


    # if "2030" in key:
    #     plot_labels = plot_labels_2030
    # else:
    #     plot_labels = plot_labels_2050

    
    # for s in list(plot_labels.keys()):
    #     handles.append(plt.Line2D([0], [0], color=color_dict[s], linewidth=15))
    #     labels.append("{}".format(s))

    if run_name.split("_")[0] == "NA":
        l1_1 = ax.legend(
            handles,
            labels,
            loc="upper left",
            bbox_to_anchor=(0.64, 0.4),
            framealpha=1,
            labelspacing=0.2,
            handletextpad=0.8,
            fontsize=16,
            handlelength=0.8,
            borderpad=0.5
        )
    else:
        l1_1 = ax.legend(
        handles,
        labels,
        loc="upper left",
        bbox_to_anchor=(0.001, 1.002),
        framealpha=1,
        labelspacing=0.2,
        handletextpad=0.8,
        fontsize=16,
        handlelength=0.8,
        borderpad=0.5
    )



    ax.add_artist(l1_1)

    dict_scenarios= {'AP':"Realistic", "BS":"Conservative", "NZ":"Optimistic"}
    # title_str="{0} | {1} Scenario | {2} TWh | {3}".format(key.split("_")[1], dict_scenarios[key.split("_")[3]], key.split("_")[4], run_name.split("_")[2])
    title_str="{0} | {1} Scenario | {2} TWh".format(key.split("_")[1], check_scenario(run_name), key.split("_")[4], run_name.split("_")[2])
    plt.title(title_str, fontsize=22) #, fontsize=14, backgroundcolor='lightgray', color='black', weight='bold', style='italic', bbox=dict(facecolor='none', edgecolor='black', boxstyle='round,pad=1'))

    # # Apply tight layout with specific adjustments
    # plt.tight_layout(pad=1.0, h_pad=1.0, w_pad=1.0, rect=[0, 0.03, 1, 0.95])

    # # Adjust margins: No padding on the sides, adjust bottom, and leave space at the top for the title
    # plt.subplots_adjust(left=0, right=1, top=0.95, bottom=0.03)

    # Before saving, calculate tight layout manually without plt.subplots_adjust
    fig.tight_layout(rect=[0, 0.03, 1, 0.95], pad=0.1, h_pad=1.0, w_pad=1.0)
    fig.set_size_inches(10.5, 9)

    if transmission==True:
        try:
            os.mkdir(os.getcwd()+'/pypsa-earth-sec/outputs/{}/maps'.format(run_name))
            os.mkdir(os.getcwd()+'/pypsa-earth-sec/outputs/{}/tables'.format(run_name))

            plt.savefig(os.getcwd()+'/pypsa-earth-sec/outputs/{}/maps/plot_map_{}_lines.png'.format(run_name, key), transparent=False,
                pdpi=300, bbox_inches="tight")

        except:
            plt.savefig(os.getcwd()+'/pypsa-earth-sec/outputs/{}/maps/plot_map_{}_lines.png'.format(run_name, key), transparent=False,
                pdpi=300, bbox_inches="tight")
    else:
        try:
            os.mkdir(os.getcwd()+'/pypsa-earth-sec/outputs/{}/maps'.format(run_name))
            os.mkdir(os.getcwd()+'/pypsa-earth-sec/outputs/{}/tables'.format(run_name))

            plt.savefig(os.getcwd()+'/pypsa-earth-sec/outputs/{}/maps/plot_map_{}.png'.format(run_name, key), transparent=False,
                dpi=300, bbox_inches="tight")

        except:
            plt.savefig(os.getcwd()+'/pypsa-earth-sec/outputs/{}/maps/plot_map_{}.png'.format(run_name, key), transparent=False,
                dpi=300, bbox_inches="tight")

    plt.close()
    #return costs
 




def plot_h2_infra(network, key, boundaries, repurposed, run_name, path_subregions, plot_h2_infra_factors):
    n = network.copy()

    # assign_location(n)

    bus_size_factor = 1e5
    linewidth_factor = plot_h2_infra_factors[run_name.split("_")[0]]['linewidth_factor']

    # MW below which not drawn
    line_lower_threshold = 1e1
    bus_color = "purple"
    link_color = "c"

    ###############################################################
    ###############################################################
    ###############################################################
    ###############################################################

    q = eval(key.split("_")[-1])
    

    #adapting bus_size_factor
    
    if q <= 10 and "2030" in key:
        
        bus_size_factor = plot_h2_infra_factors[run_name.split("_")[0]]['case_1']['bus_size_factor']

        handles = make_legend_circles_for(
            [1000, 100], scale=bus_size_factor, facecolor=bus_color
        )
        labels = ["{} GW".format(s) for s in (1, .1)] 

    elif (q <= 200 and "BS" in key) or (q <=86 and "BS" not in key and "2030" in key):

        bus_size_factor = plot_h2_infra_factors[run_name.split("_")[0]]['case_2']['bus_size_factor']

        handles = make_legend_circles_for(
            [5000, 500], scale=bus_size_factor, facecolor=bus_color
        )
        labels = ["{} GW".format(s) for s in (5, .5)]

    elif "2050" in key and "MA" in run_name:

        bus_size_factor = 5e5

        handles = make_legend_circles_for(
            [50000, 10000], scale=bus_size_factor, facecolor=bus_color
        )

        labels = ["{} GW".format(s) for s in (50, 10)]

    else:

        handles = make_legend_circles_for(
            [50000, 10000], scale=bus_size_factor, facecolor=bus_color
        )

        labels = ["{} GW".format(s) for s in (50, 10)]

    # if "2050" in key:
    #     if q <= 200 and "BS" in key:
    #         bus_size_factor = 1e4

    #         handles = make_legend_circles_for(
    #             [5000, 500], scale=bus_size_factor, facecolor=bus_color
    #         )
    #         labels = ["{} GW".format(s) for s in (5, .5)]
        

    #adapting linewidth_factor
    if "2050" in key and "NZ" in key:

        linewidth_factor = 5*1e3

    elif "2050" in key and "MA" in run_name:

        linewidth_factor = 5*1e3

    elif "2050" in key and "TR" in run_name:

        linewidth_factor = 5*1e3




############################################################
############################################################
############################################################

    n.links.loc[:, "p_nom_opt"] = n.links.loc[:, "p_nom_opt"]
    # n.links.loc[n.links.carrier == "H2 Electrolysis"].p_nom_opt

    # Drop non-electric buses so they don't clutter the plot
    n.buses.drop(n.buses.index[n.buses.carrier != "AC"], inplace=True)

    elec = n.links.index[n.links.carrier == "H2 Electrolysis"]

    bus_sizes = (
        n.links.loc[elec, "p_nom_opt"].groupby(n.links.loc[elec, "bus0"]).sum()
        / bus_size_factor
    )

    # make a fake MultiIndex so that area is correct for legend
    bus_sizes.index = pd.MultiIndex.from_product([bus_sizes.index, ["electrolysis"]])

    if repurposed:
        n.links.drop(n.links.index[(n.links.carrier != "H2 pipeline") & (n.links.carrier != "H2 pipeline repurposed")], inplace=True)
    else:
        n.links.drop(n.links.index[n.links.carrier != "H2 pipeline"], inplace=True)

    link_widths = n.links.p_nom_opt / linewidth_factor
    link_widths[n.links.p_nom_opt < line_lower_threshold] = 0.0

    n.links.bus0 = n.links.bus0.str.replace(" H2", "")
    n.links.bus1 = n.links.bus1.str.replace(" H2", "")


    fig, ax = plt.subplots(subplot_kw={"projection": ccrs.PlateCarree()})

    fig.set_size_inches(10.5, 9)

    n.plot(
        bus_sizes=bus_sizes,
        bus_colors={"electrolysis": bus_color},
        link_colors=link_color,
        link_widths=link_widths,
        branch_components=["Link"],
        color_geomap={"ocean": "lightblue", "land": "gainsboro"},
        ax=ax,
        boundaries=boundaries[run_name.split("_")[0]],
    )


    l2 = ax.legend(
        handles,
        labels,
        loc="upper left",
        bbox_to_anchor=(0.01, 1.01),
        labelspacing=0.8,
        framealpha=1.0,
        fontsize=18,
        title="Electrolyzer capacity",
        title_fontsize=18,
        handler_map=make_handler_map_to_scale_circles_as_in(ax),
    )
    ax.add_artist(l2)

    subregions = gpd.read_file(path_subregions)

    """
    subregions_new = create_shapes_uhs(key)

    qty = key.split("_")[-1]

    # subregions_uhs = subregions.loc[subregions.uhs_1000_delta != 0]
    # subregions_uhs[['uhs_0', 'uhs_1000_delta']] = subregions_uhs[['uhs_0', 'uhs_1000_delta']] / 1e6
    # subregions_uhs = subregions.loc[subregions['uhs_{}'.format(qty)] != 0]
    subregions_uhs = subregions.loc[subregions['uhs_{}'.format(qty)] > 0.0001]
    # subregions_uhs[['uhs_{}'.format(qty)]] = subregions_uhs[['uhs_{}'.format(qty)]] / 1e6

    ax.add_geometries(subregions['geometry'], facecolor='oldlace', edgecolor='dimgrey', linewidth=0.5, crs=ccrs.PlateCarree())
    
    # if uhs == 'no_export':
    vmin, vmax, vcenter = subregions_uhs['uhs_{}'.format(qty)].min(), subregions_uhs['uhs_{}'.format(qty)].max(), 0
    span = vmax - vmin
    cmap = cm.get_cmap('spring_r')
    for id, uhs in subregions_uhs.iterrows():
        color_idx = (uhs['uhs_{}'.format(qty)] - vmin) / span
        ax.add_geometries(uhs.geometry, facecolor=cmap(color_idx), alpha=0.2, edgecolor='dimgrey', linewidth=0.5, crs=ccrs.PlateCarree())

        # # Scale the geometry vertically
        # scaled_geometry = affinity.scale(uhs.geometry, xfact=1.0, yfact=0.2, origin=(0, 0))

        # ax.add_geometries([scaled_geometry], facecolor=cmap(color_idx), alpha=0.2, edgecolor='dimgrey', linewidth=0.5, crs=ccrs.PlateCarree())

    # Calculate the height of the map dynamically
    ax_bottom, ax_top = ax.get_position().get_points()[:, 1]
    map_height = ax_top - ax_bottom

    norm = colors.Normalize(vmin=vmin, vmax=vmax) 
    cbar = plt.cm.ScalarMappable(norm=norm, cmap=cmap)
    cax = fig.add_axes([0.87, ax_bottom, 0.03, map_height]) # 0.85, 0.1, 0.03, 0.8
    cbr = fig.colorbar(cbar, cax=cax)
    cbr.set_alpha(0.2)
    cbr.draw_all()
    cbr.ax.tick_params(labelsize=12) 
    cbr.set_label('Underground hydrogen storage expansion [TWh]', fontsize=13)
        
    """
    handles = []
    labels = []


    if "2050" in key and "NZ" in key and q < 1001:
        for s in (20, 5):
            handles.append(
                plt.Line2D([0], [0], color=link_color, linewidth=s * 1e3 / linewidth_factor)
            )
            labels.append("{} GW".format(s))

    elif "2050" in key and "NZ" in key and q > 1001:

        for s in (50, 10):
            handles.append(
                plt.Line2D([0], [0], color=link_color, linewidth=s * 1e3 / linewidth_factor)
            )
            labels.append("{} GW".format(s))    
    else:
        for s in (5, 1):
            handles.append(
                plt.Line2D([0], [0], color=link_color, linewidth=s * 1e3 / linewidth_factor)
            )
            labels.append("{} GW".format(s))    

    l1_1 = ax.legend(
        handles,
        labels,
        loc="upper left",
        bbox_to_anchor=(0.635, 1.01),
        framealpha=1,
        labelspacing=0.8,
        handletextpad=1.5,
        fontsize=18,
        title="H2 pipeline capacity",
        title_fontsize=18,
    )
    ax.add_artist(l1_1)


    ax.add_geometries(subregions['geometry'], facecolor='oldlace', edgecolor='dimgrey', crs=ccrs.PlateCarree())
    # fig.savefig(snakemake.output.hydrogen, bbox_inches='tight', transparent=True,
    # fig.savefig(
    #     snakemake.output.map.replace("-costs-all", "-h2_network"), bbox_inches="tight"
    # )

    dict_scenarios= {'AP':"Realistic", "BS":"Conservative", "NZ":"Optimistic"}
    # title_str="{0} | {1} Scenario | {2} TWh | {3}".format(key.split("_")[1], dict_scenarios[key.split("_")[3]], key.split("_")[4], run_name.split("_")[2])
    title_str="{0} | {1} Scenario | {2} TWh".format(key.split("_")[1], check_scenario(run_name), key.split("_")[4], run_name.split("_")[2])
    plt.title(title_str, fontsize=22) #, fontsize=14, backgroundcolor='lightgray', color='black', weight='bold', style='italic', bbox=dict(facecolor='none', edgecolor='black', boxstyle='round,pad=1'))

    # # Apply tight layout with specific adjustments
    # plt.tight_layout(pad=1.0, h_pad=1.0, w_pad=1.0, rect=[0, 0.03, 1, 0.95])

    # # Adjust margins: No padding on the sides, adjust bottom, and leave space at the top for the title
    # plt.subplots_adjust(left=0, right=1, top=0.95, bottom=0.03)

    # Before saving, calculate tight layout manually without plt.subplots_adjust
    fig.tight_layout(rect=[0, 0.03, 1, 0.95], pad=0.1, h_pad=1.0, w_pad=1.0)
    fig.set_size_inches(10.5, 9)

    # fig.savefig('report/maps/H2_infra/H2_infra_{}.pdf'.format(key), transparent=False,
    #     bbox_inches="tight")#, dpi=300)
    fig.savefig(os.getcwd()+'/pypsa-earth-sec/outputs/{}/maps/H2_infra_{}.png'.format(run_name, key), transparent=False,
        bbox_inches="tight", dpi=300)
    plt.close()
    #plt.show()





def plot_ptx_infra(network, key, run_name, plot_h2_infra_factors, boundaries, path_subregions):
    n = network.copy()

    bus_size_factor = 1e4
    linewidth_factor = plot_h2_infra_factors[run_name.split("_")[0]]['linewidth_factor']

    # MW below which not drawn
    line_lower_threshold = 1e1
    bus_color = tech_colors['ammonia']
    link_color = tech_colors['ammonia pipeline']

    ###############################################################
    ###############################################################
    ###############################################################
    ###############################################################

    q = eval(key.split("_")[-1])


    #adapting bus_size_factor

    if q <= 10 and "2030" in key:
        
        bus_size_factor = plot_h2_infra_factors[run_name.split("_")[0]]['case_1']['bus_size_factor']

        handles = make_legend_circles_for(
            [1000, 100], scale=bus_size_factor, facecolor=bus_color
        )
        labels = ["{} GW".format(s) for s in (1, .1)] 

    elif (q <= 200 and "BS" in key) or (q <=86 and "BS" not in key and "2030" in key):

        bus_size_factor = plot_h2_infra_factors[run_name.split("_")[0]]['case_2']['bus_size_factor']

        handles = make_legend_circles_for(
            [5000, 500], scale=bus_size_factor, facecolor=bus_color
        )
        labels = ["{} GW".format(s) for s in (5, .5)]

    elif "2050" in key and "MA" in run_name:

        bus_size_factor = 5e5

        handles = make_legend_circles_for(
            [50000, 10000], scale=bus_size_factor, facecolor=bus_color
        )

        labels = ["{} GW".format(s) for s in (50, 10)]

    else:

        handles = make_legend_circles_for(
            [5000, 500], scale=bus_size_factor, facecolor=bus_color
        )

        labels = ["{} GW".format(s) for s in (5, .5)]

    # if "2050" in key:
    #     if q <= 200 and "BS" in key:
    #         bus_size_factor = 1e4

    #         handles = make_legend_circles_for(
    #             [5000, 500], scale=bus_size_factor, facecolor=bus_color
    #         )
    #         labels = ["{} GW".format(s) for s in (5, .5)]
        

    #adapting linewidth_factor
    if "2050" in key and "NZ" in key:

        linewidth_factor = 5*1e3

    elif "2050" in key and "MA" in run_name:

        linewidth_factor = 5*1e3

    elif "2050" in key and "AP" in key and "TR" in run_name and q >= 500:

        linewidth_factor = 1*1e3



    ############################################################
    ############################################################
    ############################################################

    n.links.loc[:, "p_nom_opt"] = n.links.loc[:, "p_nom_opt"]
    # n.links.loc[n.links.carrier == "H2 Electrolysis"].p_nom_opt


    # Drop non-electric buses so they don't clutter the plot
    n.buses.drop(n.buses.index[n.buses.carrier != "AC"], inplace=True)

    elec = n.links.index[n.links.index.str.contains('Haber')]

    bus_sizes = (
        n.links.loc[elec, "p_nom_opt"].groupby(n.links.loc[elec, "bus0"]).sum()
        / bus_size_factor
    )


    # make a fake MultiIndex so that area is correct for legend
    bus_sizes.index = pd.MultiIndex.from_product([bus_sizes.index, ["Haber-Bosch"]])



    n.links.drop(n.links.index[n.links.carrier != "NH3 pipeline"], inplace=True)

    link_widths = n.links.p_nom_opt / linewidth_factor
    link_widths[n.links.p_nom_opt < line_lower_threshold] = 0.0

    # n.links.bus0 = n.links.bus0.str.replace(" NH3 (l)", "")
    # n.links.bus1 = n.links.bus1.str.replace(" NH3 (l)", "")
    n.links.bus0 = n.links.bus0.astype(str).str.replace(r"\s*NH3\s*\(l\)", "", regex=True)
    n.links.bus1 = n.links.bus1.astype(str).str.replace(r"\s*NH3\s*\(l\)", "", regex=True)


    fig, ax = plt.subplots(subplot_kw={"projection": ccrs.PlateCarree()})

    fig.set_size_inches(10.5, 9)

    n.plot(
        bus_sizes=bus_sizes,
        bus_colors={"Haber-Bosch": bus_color},
        link_colors=link_color,
        link_widths=link_widths,
        branch_components=["Link"],
        color_geomap={"ocean": "lightblue", "land": "gainsboro"},
        ax=ax,
        boundaries=boundaries[run_name.split("_")[0]],
    )


    l2 = ax.legend(
        handles,
        labels,
        loc="upper left",
        bbox_to_anchor=(0.01, 1.01),
        labelspacing=0.8,
        framealpha=1.0,
        fontsize=18,
        title="Electrolyzer capacity",
        title_fontsize=18,
        handler_map=make_handler_map_to_scale_circles_as_in(ax),
    )
    ax.add_artist(l2)

    subregions = gpd.read_file(path_subregions)

    """
    subregions_new = create_shapes_uhs(key)

    qty = key.split("_")[-1]

    # subregions_uhs = subregions.loc[subregions.uhs_1000_delta != 0]
    # subregions_uhs[['uhs_0', 'uhs_1000_delta']] = subregions_uhs[['uhs_0', 'uhs_1000_delta']] / 1e6
    # subregions_uhs = subregions.loc[subregions['uhs_{}'.format(qty)] != 0]
    subregions_uhs = subregions.loc[subregions['uhs_{}'.format(qty)] > 0.0001]
    # subregions_uhs[['uhs_{}'.format(qty)]] = subregions_uhs[['uhs_{}'.format(qty)]] / 1e6

    ax.add_geometries(subregions['geometry'], facecolor='oldlace', edgecolor='dimgrey', linewidth=0.5, crs=ccrs.PlateCarree())

    # if uhs == 'no_export':
    vmin, vmax, vcenter = subregions_uhs['uhs_{}'.format(qty)].min(), subregions_uhs['uhs_{}'.format(qty)].max(), 0
    span = vmax - vmin
    cmap = cm.get_cmap('spring_r')
    for id, uhs in subregions_uhs.iterrows():
        color_idx = (uhs['uhs_{}'.format(qty)] - vmin) / span
        ax.add_geometries(uhs.geometry, facecolor=cmap(color_idx), alpha=0.2, edgecolor='dimgrey', linewidth=0.5, crs=ccrs.PlateCarree())

        # # Scale the geometry vertically
        # scaled_geometry = affinity.scale(uhs.geometry, xfact=1.0, yfact=0.2, origin=(0, 0))

        # ax.add_geometries([scaled_geometry], facecolor=cmap(color_idx), alpha=0.2, edgecolor='dimgrey', linewidth=0.5, crs=ccrs.PlateCarree())

    # Calculate the height of the map dynamically
    ax_bottom, ax_top = ax.get_position().get_points()[:, 1]
    map_height = ax_top - ax_bottom

    norm = colors.Normalize(vmin=vmin, vmax=vmax) 
    cbar = plt.cm.ScalarMappable(norm=norm, cmap=cmap)
    cax = fig.add_axes([0.87, ax_bottom, 0.03, map_height]) # 0.85, 0.1, 0.03, 0.8
    cbr = fig.colorbar(cbar, cax=cax)
    cbr.set_alpha(0.2)
    cbr.draw_all()
    cbr.ax.tick_params(labelsize=12) 
    cbr.set_label('Underground hydrogen storage expansion [TWh]', fontsize=13)
        
    """
    handles = []
    labels = []


    if "2050" in key and "NZ" in key and q < 1001:
        for s in (20, 5):
            handles.append(
                plt.Line2D([0], [0], color=link_color, linewidth=s * 1e3 / linewidth_factor)
            )
            labels.append("{} GW".format(s))

    elif "2050" in key and "NZ" in key and q > 1001:

        for s in (50, 10):
            handles.append(
                plt.Line2D([0], [0], color=link_color, linewidth=s * 1e3 / linewidth_factor)
            )
            labels.append("{} GW".format(s))    
            
    elif "2050" in key and "AP" in key and q >= 500:

        for s in (10, 1):
            handles.append(
                plt.Line2D([0], [0], color=link_color, linewidth=s * 1e3 / linewidth_factor)
            )
            labels.append("{} GW".format(s)) 
    else:
        for s in (5, 1):
            handles.append(
                plt.Line2D([0], [0], color=link_color, linewidth=s * 1e3 / linewidth_factor)
            )
            labels.append("{} GW".format(s))    

    l1_1 = ax.legend(
        handles,
        labels,
        loc="upper left",
        bbox_to_anchor=(0.635, 1.01),
        framealpha=1,
        labelspacing=0.8,
        handletextpad=1.5,
        fontsize=18,
        title="NH3 pipeline capacity",
        title_fontsize=18,
    )
    ax.add_artist(l1_1)


    ax.add_geometries(subregions['geometry'], facecolor='oldlace', edgecolor='dimgrey', crs=ccrs.PlateCarree())
    # fig.savefig(snakemake.output.hydrogen, bbox_inches='tight', transparent=True,
    # fig.savefig(
    #     snakemake.output.map.replace("-costs-all", "-h2_network"), bbox_inches="tight"
    # )

    dict_scenarios= {'AP':"Realistic", "BS":"Conservative", "NZ":"Optimistic"}
    # title_str="{0} | {1} Scenario | {2} TWh | {3}".format(key.split("_")[1], dict_scenarios[key.split("_")[3]], key.split("_")[4], run_name.split("_")[2])
    title_str="{0} | {1} Scenario | {2} TWh".format(key.split("_")[1], check_scenario(run_name), key.split("_")[4], run_name.split("_")[2])
    plt.title(title_str, fontsize=22) #, fontsize=14, backgroundcolor='lightgray', color='black', weight='bold', style='italic', bbox=dict(facecolor='none', edgecolor='black', boxstyle='round,pad=1'))

    # # Apply tight layout with specific adjustments
    # plt.tight_layout(pad=1.0, h_pad=1.0, w_pad=1.0, rect=[0, 0.03, 1, 0.95])

    # # Adjust margins: No padding on the sides, adjust bottom, and leave space at the top for the title
    # plt.subplots_adjust(left=0, right=1, top=0.95, bottom=0.03)

    # Before saving, calculate tight layout manually without plt.subplots_adjust
    fig.tight_layout(rect=[0, 0.03, 1, 0.95], pad=0.1, h_pad=1.0, w_pad=1.0)
    fig.set_size_inches(10.5, 9)

    # fig.savefig('report/maps/H2_infra/H2_infra_{}.pdf'.format(key), transparent=False,
    #     bbox_inches="tight")#, dpi=300)
    fig.savefig(os.getcwd()+'/pypsa-earth-sec/outputs/{}/maps/NH3_infra_{}.png'.format(run_name, key), transparent=False,
        bbox_inches="tight", dpi=300)
    plt.close()
    #plt.show()



def check_scenario(run_name):
    h2_mode = run_name.split('_')[-1]
    nh3_mode = run_name.split('_')[4]

    if 'h2True' in h2_mode and 'free' in nh3_mode:
        scenario = 'H2 and NH3 free'

    elif 'h2True' not in h2_mode and 'free' in nh3_mode:
        scenario = 'NH3 free'

    elif 'h2True' in h2_mode and 'free' not in nh3_mode:
        scenario = 'H2 free'

    elif 'h2True' not in h2_mode and 'free' not in nh3_mode:
        scenario = 'H2 and NH3 at port'
    return scenario



def create_shapes_uhs(network, key, path_subregions):
    '''Cell to create the UHS dataframe'''
    n = network.copy()
    q = key.split("_")[-1]

    country = gpd.read_file(path_subregions)

    country['cluster'] = country.GADM_ID + '_AC'
    country = country.set_index('cluster')
    country.head()

    uhs_0 = n.stores.filter(like='H2 UHS', axis=0).set_index('bus')
    uhs_0.index = uhs_0.index.str.strip(' H2 UHS')
    country['uhs_{}'.format(q)] = uhs_0.e_nom_opt

    country['uhs_{}'.format(q)] = country['uhs_{}'.format(q)].fillna(0)

    shapes_uhs = country.copy()

    shapes_uhs.update(shapes_uhs.filter(like='uhs').apply(lambda col: col / 1e6))

    return shapes_uhs


def plot_h2_infra_UGHS(network, key, boundaries, repurposed, run_name, path_subregions, plot_h2_infra_factors):
    n = network.copy()

    # assign_location(n)

    bus_size_factor = 1e5
    linewidth_factor = plot_h2_infra_factors[run_name.split("_")[0]]['linewidth_factor']

    # MW below which not drawn
    line_lower_threshold = 1e1
    bus_color = "purple"
    link_color = "c"

    ###############################################################
    ###############################################################
    ###############################################################
    ###############################################################

    q = eval(key.split("_")[-1])
    

    #adapting bus_size_factor
    
    if q <= 10 and "2030" in key:
        
        bus_size_factor = plot_h2_infra_factors[run_name.split("_")[0]]['case_1']['bus_size_factor']

        handles = make_legend_circles_for(
            [1000, 100], scale=bus_size_factor, facecolor=bus_color
        )
        labels = ["{} GW".format(s) for s in (1, .1)] 

    elif (q <= 200 and "BS" in key) or (q <=86 and "BS" not in key and "2030" in key):

        bus_size_factor = plot_h2_infra_factors[run_name.split("_")[0]]['case_2']['bus_size_factor']

        handles = make_legend_circles_for(
            [5000, 500], scale=bus_size_factor, facecolor=bus_color
        )
        labels = ["{} GW".format(s) for s in (5, .5)]

    elif "2050" in key and "MA" in run_name:

        bus_size_factor = 5e5

        handles = make_legend_circles_for(
            [50000, 10000], scale=bus_size_factor, facecolor=bus_color
        )

        labels = ["{} GW".format(s) for s in (50, 10)]

    else:

        handles = make_legend_circles_for(
            [50000, 10000], scale=bus_size_factor, facecolor=bus_color
        )

        labels = ["{} GW".format(s) for s in (50, 10)]

    # if "2050" in key:
    #     if q <= 200 and "BS" in key:
    #         bus_size_factor = 1e4

    #         handles = make_legend_circles_for(
    #             [5000, 500], scale=bus_size_factor, facecolor=bus_color
    #         )
    #         labels = ["{} GW".format(s) for s in (5, .5)]
        

    #adapting linewidth_factor
    if "2050" in key and "NZ" in key:

        linewidth_factor = 5*1e3

    elif "2050" in key and "MA" in run_name:

        linewidth_factor = 5*1e3

    elif "2050" in key and "AP" in key and "TR" in run_name and q >= 500:

        linewidth_factor = 1*1e3



    n.links.loc[:, "p_nom_opt"] = n.links.loc[:, "p_nom_opt"]
    # n.links.loc[n.links.carrier == "H2 Electrolysis"].p_nom_opt

    # Drop non-electric buses so they don't clutter the plot
    n.buses.drop(n.buses.index[n.buses.carrier != "AC"], inplace=True)

    elec = n.links.index[n.links.carrier == "H2 Electrolysis"]

    bus_sizes = (
        n.links.loc[elec, "p_nom_opt"].groupby(n.links.loc[elec, "bus0"]).sum()
        / bus_size_factor
    )

    # make a fake MultiIndex so that area is correct for legend
    bus_sizes.index = pd.MultiIndex.from_product([bus_sizes.index, ["electrolysis"]])

    if repurposed:
        n.links.drop(n.links.index[(n.links.carrier != "H2 pipeline") & (n.links.carrier != "H2 pipeline repurposed")], inplace=True)
    else:
        n.links.drop(n.links.index[n.links.carrier != "H2 pipeline"], inplace=True)

    link_widths = n.links.p_nom_opt / linewidth_factor
    link_widths[n.links.p_nom_opt < line_lower_threshold] = 0.0

    n.links.bus0 = n.links.bus0.str.replace(" H2", "")
    n.links.bus1 = n.links.bus1.str.replace(" H2", "")


    fig, ax = plt.subplots(subplot_kw={"projection": ccrs.PlateCarree()})

    fig.set_size_inches(10.5, 9)

    n.plot(
        bus_sizes=bus_sizes,
        bus_colors={"electrolysis": bus_color},
        link_colors=link_color,
        link_widths=link_widths,
        branch_components=["Link"],
        color_geomap={"ocean": "lightblue", "land": "gainsboro"},
        ax=ax,
        boundaries=boundaries[run_name.split("_")[0]],
    )


    l2 = ax.legend(
        handles,
        labels,
        loc="upper left",
        bbox_to_anchor=(0.01, 1.01),
        labelspacing=0.8,
        framealpha=1.0,
        fontsize=18,
        title="Electrolyzer capacity",
        title_fontsize=18,
        handler_map=make_handler_map_to_scale_circles_as_in(ax),
    )
    ax.add_artist(l2)


    subregions = create_shapes_uhs(n, key, path_subregions)

    qty = key.split("_")[-1]

    subregions_uhs = subregions.loc[subregions['uhs_{}'.format(qty)] >= 0.0001]

    ax.add_geometries(subregions['geometry'], facecolor='oldlace', edgecolor='dimgrey', linewidth=0.5, crs=ccrs.PlateCarree())
    
    # if uhs == 'no_export':
    vmin, vmax, vcenter = subregions_uhs['uhs_{}'.format(qty)].min(), subregions_uhs['uhs_{}'.format(qty)].max(), 0
    if vmax == vmin:
        vmin = 0
        span = vmax - vmin
    else:
        span = vmax - vmin
    cmap = cm.get_cmap('spring_r')
    for id, uhs in subregions_uhs.iterrows():
        color_idx = (uhs['uhs_{}'.format(qty)] - vmin) / span
        ax.add_geometries(uhs.geometry, facecolor=cmap(color_idx), alpha=0.2, edgecolor='dimgrey', linewidth=0.5, crs=ccrs.PlateCarree())

        # # Scale the geometry vertically
        # scaled_geometry = affinity.scale(uhs.geometry, xfact=1.0, yfact=0.2, origin=(0, 0))

        # ax.add_geometries([scaled_geometry], facecolor=cmap(color_idx), alpha=0.2, edgecolor='dimgrey', linewidth=0.5, crs=ccrs.PlateCarree())

    # # Calculate the height of the map dynamically
    # ax_bottom, ax_top = ax.get_position().get_points()[:, 1]
    # map_height = ax_top - ax_bottom

    # norm = colors.Normalize(vmin=vmin, vmax=vmax) 
    # cbar = plt.cm.ScalarMappable(norm=norm, cmap=cmap)
    # cax = fig.add_axes([0.93, ax_bottom, 0.04, map_height]) # 0.87 0.85, 0.1, 0.03, 0.8
    # cbr = fig.colorbar(cbar, cax=cax)
    # cbr.set_alpha(0.2)
    # cbr.draw_all()
    # cbr.ax.tick_params(labelsize=20) 
    # cbr.set_label('Underground hydrogen storage expansion [TWh]', fontsize=20)
        
    

    # handles = []
    # labels = []

    # if q <= 200:
    #     handles = ana.make_legend_circles_for(
    #         [5000, 500], scale=bus_size_factor, facecolor=bus_color
    #     )
    #     labels = ["{} GW".format(s) for s in (5, .5)]

    # else:

    #     handles = ana.make_legend_circles_for(
    #         [50000, 10000], scale=bus_size_factor, facecolor=bus_color
    #     )

    #     labels = ["{} GW".format(s) for s in (50, 10)]

    l2 = ax.legend(
        handles,
        labels,
        loc="upper left",
        bbox_to_anchor=(0.01, 1.01),
        labelspacing=0.8,
        framealpha=1.0,
        fontsize=18,
        title="Electrolyzer capacity",
        title_fontsize=18,
        handler_map=make_handler_map_to_scale_circles_as_in(ax),
    )
    ax.add_artist(l2)

    handles = []
    labels = []




    if "2050" in key and "NZ" in key and q < 1001:
        for s in (20, 5):
            handles.append(
                plt.Line2D([0], [0], color=link_color, linewidth=s * 1e3 / linewidth_factor)
            )
            labels.append("{} GW".format(s))

    elif "2050" in key and "NZ" in key and q > 1001:

        for s in (50, 10):
            handles.append(
                plt.Line2D([0], [0], color=link_color, linewidth=s * 1e3 / linewidth_factor)
            )
            labels.append("{} GW".format(s))  

    elif "2050" in key and "AP" in key and q >= 500:

        for s in (10, 1):
            handles.append(
                plt.Line2D([0], [0], color=link_color, linewidth=s * 1e3 / linewidth_factor)
            )
            labels.append("{} GW".format(s)) 
    else:
        for s in (5, 1):
            handles.append(
                plt.Line2D([0], [0], color=link_color, linewidth=s * 1e3 / linewidth_factor)
            )
            labels.append("{} GW".format(s))    


    l1_1 = ax.legend(
        handles,
        labels,
        loc="upper left",
        bbox_to_anchor=(0.58, 1.01), # 0.32, 1.01
        framealpha=1,
        labelspacing=0.8, # 0.8
        handletextpad=1.5,
        fontsize=18,
        title="H2 pipeline capacity",
        title_fontsize=18,
    )
    ax.add_artist(l1_1)

    # Split the text by underscore and get the last element
    qty = key.split("_")[-1]

    # Find the index of the last and second-to-last underscores
    last_underscore_index = key.rfind("_")
    second_last_underscore_index = key.rfind("_", 0, last_underscore_index)

    # Extract the text between the last two underscores
    scenario = key[second_last_underscore_index + 1:last_underscore_index]

    # Find the index of the first and second underscores
    first_underscore_index = key.find("_")
    second_underscore_index = key.find("_", first_underscore_index + 1)

    # Extract the text between the first two underscores
    year = key[first_underscore_index + 1:second_underscore_index]

    # # Set the y-label for the whole figure
    # fig.text(0.38, 0.7, '{} {} {} TWh'.format(year, scen_dict[scenario], qty), va='center', rotation='horizontal', fontdict={'fontsize': 14},
    #         bbox=dict(facecolor='oldlace', edgecolor='black', boxstyle='round'))

    dict_scenarios= {'AP':"Realistic", "BS":"Conservative", "NZ":"Optimistic"}
    # title_str="{0} | {1} Scenario | {2} TWh | {3}".format(key.split("_")[1], check_scenario(run_name), key.split("_")[4], run_name.split("_")[2])
    title_str="{0} | {1} Scenario | {2} TWh".format(key.split("_")[1], check_scenario(run_name), key.split("_")[4], run_name.split("_")[2])
    plt.title(title_str, fontsize=22) #, fontsize=14, backgroundcolor='lightgray', color='black', weight='bold', style='italic', bbox=dict(facecolor='none', edgecolor='black', boxstyle='round,pad=1'))


    # Calculate the height of the map dynamically
    ax_bottom, ax_top = ax.get_position().get_points()[:, 1]
    map_height = ax_top - ax_bottom

    norm = colors.Normalize(vmin=vmin, vmax=vmax) 
    cbar = plt.cm.ScalarMappable(norm=norm, cmap=cmap)
    cax = fig.add_axes([0.87, ax_bottom, 0.04, map_height]) # 0.87 0.85, 0.1, 0.03, 0.8
    cbr = fig.colorbar(cbar, cax=cax)
    cbr.set_alpha(0.2)
    cbr.draw_all()
    cbr.ax.tick_params(labelsize=18) 
    cbr.set_label('Underground hydrogen storage expansion [TWh]', fontsize=18)

    # # Set the y-label for the whole figure
    # fig.text(0.38, 0.85, '{} {} {} TWh'.format(year, scen_dict[scenario], qty), va='center', rotation='horizontal', fontdict={'fontsize': 14},
    #         bbox=dict(facecolor='oldlace', edgecolor='black', boxstyle='round'))

    # fig.savefig(snakemake.output.hydrogen, bbox_inches='tight', transparent=True,
    # fig.savefig(
    #     snakemake.output.map.replace("-costs-all", "-h2_network"), bbox_inches="tight"
    # )

    # # Before saving, calculate tight layout manually without plt.subplots_adjust
    # fig.tight_layout(rect=[0, 0.03, 1, 0.95], pad=0.1, h_pad=1.0, w_pad=1.0)
    # fig.set_size_inches(10.5, 9)

    # fig.savefig('report/maps/H2_infra/H2_infra_{}.pdf'.format(key), transparent=False,
    #     bbox_inches="tight")#, dpi=300)
    fig.savefig(os.getcwd()+'/pypsa-earth-sec/outputs/{}/maps/H2_infra_UHS_{}.png'.format(run_name, key), transparent=False,
        bbox_inches="tight", dpi=300)
    plt.close()
    #plt.show()