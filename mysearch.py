"""ESGF API Search Results to Pandas Dataframes
"""
import requests
import numpy
from myconfig import target_format, node_pref
import pandas as pd

# Author: Unknown
# I got the original version from a word document published by ESGF
# https://docs.google.com/document/d/1pxz1Kd3JHfFp8vR2JCVBfApbsHmbUQQstifhGNdc6U0/edit?usp=sharing
# API AT:
# https://github.com/ESGF/esgf.github.io/wiki/ESGF_Search_REST_API#results-pagination

def esgf_search(search, server="https://esgf-node.llnl.gov/esg-search/search",
                files_type="HTTPServer", local_node=True,
                project="CMIP6", page_size=500, verbose=False,
                format="application%2Fsolr%2Bjson", toFilter=True):

    client = requests.session()
    payload = search
    payload["project"] = project
    payload["type"]= "File"
    if local_node:
        payload["distrib"] = "false"

    payload["format"] = format
    payload["limit"] = 500

    numFound = 10000
    all_frames = []
    offset = 0
    while offset < numFound:
        payload["offset"] = offset
        url_keys = []
        for k in payload:
            url_keys += ["{}={}".format(k, payload[k])]

        url = "{}/?{}".format(server, "&".join(url_keys))
        r = client.get(url)
        r.raise_for_status()
        resp = r.json()["response"]
        numFound = int(resp["numFound"])
        
        resp = resp["docs"]
        offset += len(resp)
        #print(offset,numFound,len(resp))
        for d in resp:
            dataset_id = d["dataset_id"]
            dataset_size = d["size"]
            for f in d["url"]:
                sp = f.split("|")
                if sp[-1] == files_type:
                    url = sp[0]
                    if sp[-1] == 'OPENDAP':
                        url = url.replace('.html', '')
                    dataset_url = url
            all_frames += [[dataset_id,dataset_url,dataset_size]]
        
    ddict = {}
    item = 0
    for item, alist in enumerate(all_frames):
        dataset_id = alist[0]
        dataset_url = alist[1]
        dataset_size = alist[2]
        vlist = dataset_id.split('|')[0].split('.')[-9:]
        vlist += [dataset_url.split('/')[-1]]
        vlist += [dataset_size]
        vlist += [dataset_url]
        vlist += [dataset_id.split('|')[-1]]
        ddict[item] = vlist
        item += 1

    dz = pd.DataFrame.from_dict(ddict, orient='index')
    if len(dz) == 0:
       print('empty search response')
       return dz

    dz = dz.rename(columns={0: "activity_id", 1: "institution_id", 2:"source_id", 
                            3:"experiment_id",4:"member_id",5:"table_id",
                            6:"variable_id",7:"grid_label",8:"version_id",
                            9:"ncfile",10:"file_size",11:"url",12:"data_node"})

    
    dz['ds_dir'] = dz.apply(lambda row: target_format % row,axis=1)
    dz['node_order'] = [node_pref[s] for s in dz.data_node ]
    dz['start'] = [s.split('_')[-1].split('-')[0] for s in dz.ncfile ]
    dz['stop'] = [s.split('_')[-1].split('-')[-1].split('.')[0] for s in dz.ncfile ]


    if toFilter:
       # remove all 999 nodes
       dz = dz[dz.node_order != 999]

       # keep only best node 
       dz = dz.sort_values(by=['node_order'])
       dz = dz.drop_duplicates(subset =["ds_dir","ncfile","version_id"],keep='first')

       # keep only most recent version from best node
       dz = dz.sort_values(by=['version_id'])
       dz = dz.drop_duplicates(subset =["ds_dir","ncfile"],keep='last')

    return dz
