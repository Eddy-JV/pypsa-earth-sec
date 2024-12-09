
import ruamel.yaml

file_paths = [#'/nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/config_2050_cons.yaml',
            '/nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/config_2050_opt.yaml',
            '/nimble/home/edd32710/projects/Paper_1/pypsa-earth-sec/config_2050_real.yaml']


# Read the YAML file
yaml = ruamel.yaml.YAML()

for file_path in file_paths:
    with open(file_path, 'r') as file:
        yaml_content = yaml.load(file)

    # Modify the desired line (e.g., change a value)

    # if yaml_content['sector']['hydrogen']['network']:
    if yaml_content["sector"]["hydrogen"]["electrolysis"] == 'free':
        h2_freedom = 'h2Free'
    else:
        h2_freedom = 'h2Port'

    yaml_content['run']['name'] = 'TR_{}_{}_{}_20241113{}'.format(yaml_content['scenario']['planning_horizons'][0], yaml_content['export']['esc_scenarios']['esc'][0], yaml_content['export']['esc_scenarios']['synthesis'], h2_freedom)

    yaml_content['scenario']['clusters'] = [yaml_content['scenario']['clusters'][0] + 3]

    yaml_content['export']['h2export'] = [yaml_content['export']['h2export_all_quantities'][0]]

    yaml_content['policy_config']['hydrogen']['is_reference'] = True

    # Write the updated YAML back to the file
    with open(file_path, 'w') as file:
        yaml.dump(yaml_content, file)