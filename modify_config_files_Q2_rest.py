
import ruamel.yaml
import os

file_paths = [#'/nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/config_2030_cons.yaml',
            #'/nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/config_2030_opt.yaml',
            # '/nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/config_2030_real.yaml',
            #'/nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/config_2050_cons.yaml',
            '/nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/config_2050_opt.yaml',
            '/nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/config_2050_real.yaml'
            ]


# Read the YAML file
yaml = ruamel.yaml.YAML()

for file_path in file_paths:
    with open(file_path, 'r') as file:
        yaml_content = yaml.load(file)

    # Modify the desired line (e.g., change a value)

    yaml_content['export']['h2export'] = yaml_content['export']['h2export_all_quantities'][1:]

    yaml_content['policy_config']['hydrogen']['is_reference'] = False



    run = yaml_content['run']['name']
    folder_path = 'results/{}/postnetworks/'.format(run)

    # List all files in the folder
    # file_names = [f for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f))]
    file_names = [os.path.join(folder_path, f) for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f))]

    yaml_content['policy_config']['hydrogen']['path_to_ref'] = '/nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/' + file_names[0]

    # cluster_info = {}
    # rate_info = {}

    # # Extract clusters and rate data from 2030 runs:
    # for file_name in file_names:
    #     cluster_info[file_name.split("_")[-2]] = int(file_name.split("_")[-9])
    #     rate_info[file_name.split("_")[-2]] = file_name.split("_")[-3]

    
    # # Change the existing_params in config files of 2050 runs:
    # for file_path in file_paths_2050:
    #     with open(file_path, 'r') as file:
    #         yaml_content_2050 = yaml.load(file)

    #     ex_quantities_2050 = yaml_content_2050['export']['h2export_all_quantities']
        

    #     yaml_content_2050 ['custom_data']['existing_params']['run'] = run
    #     yaml_content_2050 ['custom_data']['existing_params']['H'] = 3
    #     yaml_content_2050 ['custom_data']['existing_params']['year'] = 2030

    #     if yaml_content_2050 ['scenario']['demand'][0] == 'BS':
    #         yaml_content_2050 ['custom_data']['existing_params']['demand'] = 'BS'
    #         yaml_content_2050 ['custom_data']['existing_params']['clusters'] = cluster_info['BS']
    #         yaml_content_2050 ['custom_data']['existing_params']['rate'] = rate_info['BS']

    #     elif yaml_content_2050 ['scenario']['demand'][0] == 'AP':
    #         yaml_content_2050 ['custom_data']['existing_params']['demand'] = 'AP'
    #         yaml_content_2050 ['custom_data']['existing_params']['clusters'] = cluster_info['AP']
    #         yaml_content_2050 ['custom_data']['existing_params']['rate'] = rate_info['AP']

    #     elif yaml_content_2050 ['scenario']['demand'][0] == 'NZ':
    #         yaml_content_2050 ['custom_data']['existing_params']['demand'] = 'NZ'
    #         yaml_content_2050 ['custom_data']['existing_params']['clusters'] = cluster_info['NZ']
    #         yaml_content_2050 ['custom_data']['existing_params']['rate'] = rate_info['NZ']
        
    #         # Write the updated YAML back to the file
    #     with open(file_path, 'w') as file:
    #         yaml.dump(yaml_content_2050, file)


    # Write the updated YAML back to the file
    with open(file_path, 'w') as file:
        yaml.dump(yaml_content, file)