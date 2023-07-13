import numpy as np
import pandas as pd
import os
import psutil
import random
import time
import logging
from skfeature.function.information_theoretical_based import LCSI
from sklearn.feature_selection import chi2
from sklearn.feature_selection import mutual_info_classif
from scipy.stats import mannwhitneyu
from statsmodels.stats.multitest import fdrcorrection
from sklearn.utils import resample
import multiprocessing as mp
from multiprocessing import Pool
from shared_objects import SharedNumpyArray, SharedPandasDataFrame
'''
This class is meant to be used to do feature selection after you have compiled your
final dataset. Check an example usage at the end of this file.
'''
def compile_snps(snps, factors, dir, out):
    '''
    Compile a dataframe of given list of SNPs across all chrom files. Output as .csv.

    Arguments
        snps (set(str)) -- set of snps to be compiled.
        factors (list(str)) -- LIST of fix columns (Sex, ID_1, PHQ9_binary)
        dir (str) -- path to directory of chrom files. this directory should only contain .csv files of the chroms
        out_file (str) -- path to folder to output the result
    '''
    logging.basicConfig(filename= os.path.join(os.path.dirname(out), 'compiler.log'), encoding='utf-8', level=logging.DEBUG)
    files = [file for file in os.listdir(dir) if '.csv' in file]
    individual_args = [(os.path.join(dir, file), snps, factors) for file in files]
    
    with Pool() as pool:
        results = pool.map(compile_wrapper, individual_args)

    final = pd.concat(results, axis = 1)
    final = final.loc[:,~final.columns.duplicated()].copy()

    final.to_csv(os.path.join(out))
        
def compile_wrapper(args):
    '''
    Used for parallelization in compiling a list of SNPs from all chrom files.

    Arguments:
        args (tuple) -- a tuple that should contain two fields
            args[0] (str) -- path to chrom .csv file
            args[1] (set(str)) -- set of SNP columns to be compiled
            args[2] (list(str)) -- list of fix columns (Sex, ID_1, PHQ9_binary)
    '''
    logging.info('pid: {}. Working on {}.'.format(os.getpid(), args[0]))
    df = pd.read_csv(args[0], index_col = 0)
    snp_set = set(df.columns.tolist())
    snps_present = args[1].intersection(snp_set)
    logging.info('pid: {}. Found {} SNPs on {}.'.format(os.getpid(), str(len(snps_present)), args[0]))
    df.sort_values('ID_1', inplace = True)
    result = []
    sum_na = 0
    for snp in snps_present:
        this_na = df[snp].isna().sum()
        sum_na += this_na
        logging.info('{} has {} NaN values'.format(snp, str(this_na)))
        result.append(df[snp])
    for col in args[2]:
        result.append(df[col])
    logging.info('{} has {} NaN in total out of {}'.format(os.path.basename(args[0]), str(sum_na), len(df.index)))
    return pd.concat(result, axis = 1)

def fs_wrapper(args):
    '''
    Used for parallelization in univariate feature selection.

    Arguments:
        args (tuple) -- a tuple that should contain five fields
            args[0] (str) -- rsid of snp
            args[1] (shared_objects.SharedPandasDataFrame) -- reference to shared df object
            args[2] (shared_objects.SharedNumpyArray) -- reference to shared target arr object
            args[3] (str) -- name of feature selection function
    Returns:
        result (any) -- whatever is returned from passed feat select function
        args[0] (str) -- rsid of snp
        frequency (int) -- how many times this snp appeared in the population
    '''
    start = time.time()
    data = args[1].read()
    target = args[2].read()
    predictor = np.reshape(data[args[0]].to_numpy(), (-1, 1))
    frequency = data[args[0]].sum()
    if args[3] == 'infogain':
        result = mutual_info_classif(predictor, target, random_state = 0)
    elif args[3] == 'chi2':
        result = chi2(predictor, target)
    elif args[3] == 'mwu':
        zero_vector = target[np.where(data[args[0]] == 0)]
        one_vector = target[np.where(data[args[0]] == 1)]
        if len(zero_vector) == 0 or len(one_vector) == 0:
            u1 = np.inf
            u2 = np.inf
            p = np.nan
        else:
            u1, p = mannwhitneyu(zero_vector, one_vector)
            u2, _ = mannwhitneyu(one_vector, zero_vector)
        result = (u1, u2, p)
    else:
        raise Exception('Unrecognized feature selection function name: {}'.format(args[3]))
    duration = time.time() - start
    logging.info('CHILD --- pid: {}. Completed a test for {} at {} in {} seconds. Currently using {} MB memory.'
                 .format(os.getpid(), args[0], time.ctime(), duration, psutil.Process(os.getpid()).memory_info().rss / 1024 ** 2))
    return result, args[0], frequency

def chisquare(data, target, out_name, kwargs):
    '''
    Runs parallelized chi-square feature selection on the data and the target values. Outputs
    results to a .csv at given path

    Arguments:
        data (DataFrame) -- dataset
        target (str) -- target column label in dataset
        out_name (str) -- path where the results will be outputted
    '''
    start_time = time.time()
    logging.info('PARENT --- Started rounds of feature selection at: ' + time.ctime())
    target_arr = data[target].to_numpy().astype('int')
    only_snp_data = data.drop(columns = [target, 'ID_1'])

    shared_snp_data = SharedPandasDataFrame(only_snp_data)
    shared_target_arr = SharedNumpyArray(target_arr)
    
    individual_args = [(snp, shared_snp_data, shared_target_arr, 'chi2') for snp in only_snp_data]

    parallel_time = time.time()
    logging.info('PARENT --- Started parallelization of feature selection at: ' + time.ctime())
    logging.info('PARENT --- Overhead to start parallelizing: ' + (str(parallel_time - start_time)))
    with Pool() as pool:
        results = pool.map(fs_wrapper, individual_args)
    shared_snp_data.unlink()
    shared_target_arr.unlink()
    
    end_time = time.time()
    logging.info('PARENT --- Stopped parallelization of feature selection at: ' + time.ctime())
    logging.info('PARENT --- Parallelized step took: ' + (str(end_time - parallel_time)))

    df = pd.DataFrame()
    df["SNP"] = [result[1] for result in results]
    df["chi2_score"] = [result[0][0][0] for result in results]
    df["p_val"] = [result[0][1][0] for result in results]
    df['frequency'] = [result[2] for result in results]
    df.sort_values(by="chi2_score", inplace=True, ascending = False)

    df.to_csv(out_name)

def infogain(data, target, out_name, kwargs):
    '''
    Runs infogain feature selection on the data and the target values. Outputs
    results to a .csv at given path

    Arguments:
        data (DataFrame) -- dataset
        target (str) -- target column label in dataset
        outname (str) -- path where the results will be outputted
    '''
    start_time = time.time()
    logging.info('PARENT --- Started rounds of feature selection at: ' + time.ctime())
    target_arr = data[target].to_numpy().astype('int')
    only_snp_data = data.drop(columns = [target, 'ID_1'])

    shared_snp_data = SharedPandasDataFrame(only_snp_data)
    shared_target_arr = SharedNumpyArray(target_arr)
    
    individual_args = [(snp, shared_snp_data, shared_target_arr, 'infogain') for snp in only_snp_data]

    parallel_time = time.time()
    logging.info('PARENT --- Started parallelization of feature selection at: ' + time.ctime())
    logging.info('PARENT --- Overhead to start parallelizing: ' + (str(parallel_time - start_time)))
    with Pool() as pool:
        results = pool.map(fs_wrapper, individual_args)
    shared_snp_data.unlink()
    shared_target_arr.unlink()

    end_time = time.time()
    logging.info('PARENT --- Stopped parallelization of feature selection at: ' + time.ctime())
    logging.info('PARENT --- Parallelized step took: ' + (str(end_time - parallel_time)))
    
    df = pd.DataFrame()
    df["SNP"] = [result[1] for result in results]
    df["infogain_score"] = [result[0][0] for result in results]
    df['frequency'] = [result[2] for result in results]
    df.sort_values(by="infogain_score", inplace=True, ascending = False)
    
    df.to_csv(out_name)

def mann_whitney_u(data, target, out_name, kwargs):
    '''
    Runs infogain feature selection on the data and the target values. Outputs
    results to a .csv at given path

    Arguments:
        data (DataFrame) -- dataset
        target (str) -- target column label in dataset
        outname (str) -- path where the results will be outputted
    '''
    start_time = time.time()
    logging.info('PARENT --- Started rounds of feature selection at: ' + time.ctime())
    target_arr = data[target].to_numpy().astype('int')
    only_snp_data = data.drop(columns = [target, 'ID_1'])

    shared_snp_data = SharedPandasDataFrame(only_snp_data)
    shared_target_arr = SharedNumpyArray(target_arr)
    
    individual_args = [(snp, shared_snp_data, shared_target_arr, 'mwu') for snp in only_snp_data]

    parallel_time = time.time()
    logging.info('PARENT --- Started parallelization of feature selection at: ' + time.ctime())
    logging.info('PARENT --- Overhead to start parallelizing: ' + (str(parallel_time - start_time)))
    with Pool() as pool:
        results = pool.map(fs_wrapper, individual_args)
    shared_snp_data.unlink()
    shared_target_arr.unlink()

    end_time = time.time()
    logging.info('PARENT --- Stopped parallelization of feature selection at: ' + time.ctime())
    logging.info('PARENT --- Parallelized step took: ' + (str(end_time - parallel_time)))
    
    df = pd.DataFrame()
    df["SNP"] = [result[1] for result in results]
    df["mwu_1"] = [result[0][0] for result in results]
    df["mwu_2"] = [result[0][1] for result in results]
    df["u_min"] = [min(result[0][0], result[0][1]) for result in results]
    df["p_val"] = [result[0][2] for result in results]
    df['frequency'] = [result[2] for result in results]
    df.sort_values(by="u_min", inplace=True)
    
    df.to_csv(out_name)

def mrmr(data, target, out_name, kwargs):
    '''
    Applies MRMR feature selection on the data and target values. Outputs
    results to a .csv at given path

    Arguments:
        data (DataFrame) -- dataset
        target (str) -- target column label in dataset
        outname (str) -- path where the results will be outputted
    ---------
    Brown, Gavin et al. "Conditional Likelihood Maximisation: A Unifying Framework for Information Theoretic Feature Selection." JMLR 2012.
    '''
    target_arr = data[target].to_numpy().astype('int')
    only_snp_data = data.drop(columns = [target, 'ID_1'])
    data_arr = only_snp_data.to_numpy()
    
    if 'n_selected_features' in kwargs.keys():
        logging.info('Yay this did print!')
        n_selected_features = kwargs['n_selected_features']
        F, J_CMI, MIfy= LCSI.lcsi(data_arr, target_arr, gamma=0, function_name='MRMR', n_selected_features=n_selected_features)
    else:   
        logging.info('This shouldn\'t print')
        F, J_CMI, MIfy = LCSI.lcsi(data_arr, target_arr, gamma=0, function_name='MRMR')

    logging.info('MRMR --- Chosen indices are: {}'.format(F))
    logging.info('MRMR --- Therefore, chosen SNPs are: '.format(only_snp_data.columns[F]))
    df = pd.DataFrame()
    df['SNP'] = only_snp_data.columns.tolist()
    df['mrmr_score'] = 0
    df.reset_index(drop = True, inplace = True)
    df.loc[F, 'mrmr_score'] = 1
    df.to_csv(out_name)

def mrmr_parallel(data, target, out_name, kwargs):
    target_arr = data[target].to_numpy().astype('int')
    only_snp_data = data.drop(columns = [target, 'ID_1'])
    data_arr = only_snp_data.to_numpy()

    feat_selector = mifs.MutualInformationFeatureSelector(method = 'MRMR')
    feat_selector.fit(data_arr,  target_arr)
    df = pd.DataFrame()
    chosen_snps = []
    for index in F:
        chosen_snps.append(list(only_snp_data.columns)[index])
    df['SNP'] = only_snp_data.columns.tolist()
    df['mrmr_score'] = np.zeros(len(df)).tolist()
    df[df['SNP'].isin(chosen_snps), 'mrmr_score'] = 1
    df.to_csv(out_name)
    
def jmi(data, target, out_name, kwargs):
    '''
    Applies MRMR feature selection on the data and target values. Outputs
    results to a .csv at given path

    Arguments:
        data (DataFrame) -- dataset
        target (str) -- target column label in dataset
        outname (str) -- path where the results will be outputted
    ---------
    Brown, Gavin et al. "Conditional Likelihood Maximisation: A Unifying Framework for Information Theoretic Feature Selection." JMLR 2012.
    '''

    target_arr = data[target].to_numpy().astype('int')
    only_snp_data = data.drop(columns = [target, 'ID_1'])
    data_arr = only_snp_data.to_numpy()
    
    if 'n_selected_features' in kwargs.keys():
        logging.info('Yay this did print!')
        n_selected_features = kwargs['n_selected_features']
        F, J_CMI, MIfy = LCSI.lcsi(data_arr, target_arr, function_name='JMI', n_selected_features=n_selected_features)
    else:
        logging.info('This shouldn\'t print!')
        F, J_CMI, MIfy = LCSI.lcsi(data_arr, target_arr, function_name='JMI')

    logging.info('JMI --- Chosen indices are: {}'.format(F))
    logging.info('JMI --- Therefore, chosen SNPs are: '.format(only_snp_data.columns[F]))
    df = pd.DataFrame()
    df['SNP'] = only_snp_data.columns.tolist()
    df['jmi_score'] = 0
    df.reset_index(drop = True, inplace = True)
    df.loc[F, 'jmi_score'] = 1
    df.to_csv(out_name)

class FeatureSelector():
    # TODO: implement init
    def __init__(
        self,
        data,
        out_folder
    ):
        '''
        Arguments:
            data (DataFrame) -- dataset that contains features and target. should only contain features that will undergo feature selection, the ID_1 column, and the target column
            out_folder (str) -- path of directory where this instance will output files (created if non-existent)
        '''
        self.data = data
        self.out_folder = out_folder

        if not os.path.exists(out_folder):
            os.makedirs(out_folder)

        logging.basicConfig(filename= os.path.join(out_folder, 'feature_selector.log'), encoding='utf-8', level=logging.DEBUG)

    def bootstrap(self, n_samples = None, stratify_column = None):
        '''
        Returns a n_samples size resampling of self.data with replacements, stratified according to stratify_column

        Arguments:
            n_samples (int) -- sample size. pass None to use self.data size
            stratify_column (str) -- label of column to stratify according to. pass None for no stratifying

        Returns:
            result (DataFrame) -- dataframe that is resampled from self.data
        '''
        if stratify_column is not None:
            stratify_column = self.data[stratify_column].to_numpy()
        return resample(self.data, n_samples = n_samples, stratify = stratify_column)

    @staticmethod 
    def load_bootstraps(file):
        '''
        Read a list of bootstrap participant ID's from given dataframe, and return it.
        Useful for maintaining the same sample across different runs.

        Arguments:
            file (str) -- path to the .csv file containing the bootstraps, where every column
                should be a list of ID_1's for a bootstrap.

        Returns:
            bootstraps (list(list(int))) -- nested list of ID_1's for every bootstrap
        '''
        bootstraps = []
        df = pd.read_csv(file, index_col = 0)
        for col in df.columns:
            bootstraps.append(df[col].tolist())
        return bootstraps

    def get_sample_from_ids(self, ids):
        '''
        Return a dataframe containing the participants with given list of ids

        Arguments:
            ids (list(int)) -- list of ID_1's (can have repetitions)

        Returns:
            sample (DataFrame) -- sample from self.data containing participants with given ids
        '''
        rows = []
        for id in ids:
            rows.append(self.data.loc[self.data['ID_1'] == id])
        return pd.concat(rows)

    def bootstrapped_feat_select(
        self, 
        n_bootstraps,
        n_samples,
        stratify_column, 
        selectors, 
        selector_names,
        selector_kwargs,
        out_name, 
        bootstraps = None,
    ):
        '''
        Bootstraps the dataset, applies feature selection with specified functions.
        Compiles results across all and outputs them as a .csv file.

        Arguments:
            n_bootstraps (int) -- number of bootstraps. ignored if bootstraps is not None.
            n_samples (int) -- number of samples in each bootstrap. ignored if bootstraps is not None.
            stratify_column (str) -- column label to use for feature selection and stratifying the bootstrap.
            selectors (list(function)) -- list of functions to use for feature selection. 
            selector_names (list(str)) -- list of function names that will be used to name subdirectories.
            selector_kwargs (list(dict(str: any))) -- list of dictionaries for kwargs to pass into selector functions
            out_name (str) -- name of subdirectories and compiled results file that will be created
            bootstraps (list(list(int))) -- if not None, use this to create samples instead of creating new random samples
        ''' 
        if len(selectors) != len(selector_names):
            raise Exception('Selector list must be as long as selector name list')

        if len(selectors) != len(selector_kwargs):
            raise Exception('Selector list must be as long as selector kwargs list')

        if bootstraps is not None:
            n_bootstraps = len(bootstraps)

        filenames = []
        bootstrap_export = []
        logging.info('PARENT --- Parent process is using {} MB of memory.'.format(psutil.Process(os.getpid()).memory_info().rss / 1024 ** 2))

        for i in range(n_bootstraps):
            start = time.time()
            logging.info('PARENT --- Trying to create a bootstrap sample.')
            if bootstraps is not None:
                this_sample = self.get_sample_from_ids(bootstraps[i])
                bootstrap_export.append(bootstraps[i])
                logging.info('PARENT --- Loaded sample from provided bootstrap in {} seconds'.format(str(time.time() - start)))
            else:
                this_sample = self.bootstrap(n_samples = n_samples, stratify_column = stratify_column)
                bootstrap_export.append(this_sample['ID_1'].tolist())
                logging.info('PARENT --- Created new in {} seconds'.format(str(time.time() - start)))
            for j in range(len(selectors)):
                function = selectors[j]
                selector_folder = os.path.join(self.out_folder, out_name + '_' + selector_names[j])
                if not os.path.exists(selector_folder):
                    os.makedirs(selector_folder)
                    logging.info('made a folder ' + selector_folder)
                filename = os.path.join(selector_folder, selector_names[j] + '_' + str(i) + '.csv')
                logging.info('PARENT --- Started {} at {}'.format(selector_names[j], time.ctime()))
                start = time.time()
                function(this_sample, stratify_column, filename, selector_kwargs[j])
                logging.info('PARENT --- Finished {} at {}. That took {}'.format(selector_names[j], time.ctime(), str(time.time() - start)))
                filenames.append(filename)

        final = pd.DataFrame()
        snps = pd.read_csv(filenames[0])['SNP']
        final['SNP'] = snps
        for name in selector_names:
            final['total_' + name] = np.zeros(len(snps))
            final['nan_' + name] = np.zeros(len(snps))
        for file in filenames:
            curr_file = pd.read_csv(file)
            if 'chi2' in file:
                total_column = 'total_chi2'
                nan_column = 'nan_chi2'
                target_column = 'chi2_score'
            elif 'infogain' in file:
                total_column = 'total_infogain'
                nan_column = 'nan_infogain'
                target_column = 'infogain_score'
            elif 'mrmr' in file:
                total_column = 'total_mrmr'
                nan_column = 'nan_mrmr'
                target_column = 'mrmr_score'
            elif 'jmi' in file:
                total_column = 'total_jmi'
                nan_column = 'nan_jmi'
                target_column = 'jmi_score'
            for snp in final['SNP']:
                result = curr_file.loc[curr_file['SNP'] == snp, target_column]
                if result.isna().item():
                    final.loc[final['SNP'] == snp, nan_column] += 1
                else:
                    final.loc[final['SNP'] == snp, total_column] += curr_file.loc[curr_file['SNP'] == snp, target_column].item()
        final
        for name in selector_names:
            final['average_' + name] = final['total_' + name] / ((final['nan_' + name] * -1) + n_bootstraps)
        final.to_csv(os.path.join(self.out_folder, out_name + '.csv'))

        bootstrap_df = pd.DataFrame()
        for i in range(len(bootstrap_export)):
            name = 'bootstrap_' + str(i + 1)
            bootstrap_df[name] = bootstrap_export[i]

        bootstrap_df.to_csv(os.path.join(self.out_folder, out_name + '_bootstraps.csv'))
            

'''
Below is an example usage
'''

'''
def main():
    data = pd.read_csv('/home/mminbay/summer_research/summer23_aylab/data/imputed_data/final_data/final_depression_allsnps_6000extra_c1.csv', index_col = 0)

    data.drop(columns = ['Sex'], inplace = True)
    
    fselect = FeatureSelector(
        data, 
        '/home/mminbay/summer_research/summer23_aylab/data/feat_select/'
    )
    fselect.bootstrapped_feat_select(10, 1000, 'PHQ9_binary', 1, [fselect.chisquare, fselect.infogain], ['chi2', 'infogain'], 'test')
    
if __name__ == '__main__':
    main()
'''
            
        
        
    
    