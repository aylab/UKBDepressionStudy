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
from sklearn.linear_model import Lasso, LogisticRegression
from scipy.stats import mannwhitneyu, ttest_ind
from statsmodels.stats.multitest import fdrcorrection
from sklearn.utils import resample
import multiprocessing as mp
from multiprocessing import Pool
from shared_objects import SharedNumpyArray, SharedPandasDataFrame
'''
This class is meant to be used to do feature selection after you have compiled your
final dataset. Check an example usage at the end of this file.
'''
def fs_wrapper(args):
    '''
    DO NOT CALL DIRECTLY
    Used for parallelization in univariate feature selection.

    Arguments:
        args (tuple) -- a tuple that should contain five fields
            args[0] (str) -- rsid of snp
            args[1] (shared_objects.SharedPandasDataFrame) -- reference to shared df object
            args[2] (shared_objects.SharedNumpyArray) -- reference to shared target arr object
            args[3] (str) -- name of feature selection function
    Returns:
        result (dict(str: any)) -- whatever is returned from passed feat select function
        args[0] (str) -- rsid of snp
        frequency (int) -- how many times this snp appeared in the population
    '''
    start = time.time()
    data = args[1].read()
    target = args[2].read()
    predictor = np.reshape(data[args[0]].to_numpy(), (-1, 1))
    frequency = data[args[0]].sum()
    result = {}
    if args[3] == 'infogain':
        result['score'] = mutual_info_classif(predictor, target, random_state = 0)[0]
    elif args[3] == 'chi2':
        score, p_val = chi2(predictor, target)
        result['score'] = score[0]
        result['p_val'] = p_val[0]
    elif args[3] == 'mwu':
        zero_vector = target[np.where(data[args[0]] == 0)]
        one_vector = target[np.where(data[args[0]] == 1)]
        if len(zero_vector) == 0 or len(one_vector) == 0:
            u1 = np.nan
            u2 = np.nan
            p_val = np.nan
        else:
            u1, p_val = mannwhitneyu(zero_vector, one_vector)
            u2, _ = mannwhitneyu(one_vector, zero_vector)
        result['score_1'] = u1
        result['score_2'] = u2
        result['p_val'] = p_val
    elif args[3] == 'ttest':
        zero_vector = target[np.where(data[args[0]] == 0)]
        one_vector = target[np.where(data[args[0]] == 1)]
        if len(zero_vector) == 0 or len(one_vector) == 0:
            t_stat = np.nan
            p_val = np.nan
        else:
            t_stat, p_val = ttest_ind(zero_vector, one_vector)
        result['score'] = t_stat
        result['p_val'] = p_val
    else:
        raise Exception('Unrecognized feature selection function name: {}'.format(args[3]))
    duration = time.time() - start
    logging.info('CHILD --- pid: {}. Completed a test for {} at {} in {} seconds. Currently using {} MB memory.'
                 .format(os.getpid(), args[0], time.ctime(), duration, psutil.Process(os.getpid()).memory_info().rss / 1024 ** 2))
    return result, args[0], frequency

def chisquare(data, target, out_name, kwargs):
    '''
    DO NOT CALL DIRECTLY
    Runs parallelized chi-square feature selection on the data and the target values. Outputs
    results to a .csv at given path

    Arguments:
        data (DataFrame) -- dataset
        target (str) -- target column label in dataset
        out_name (str) -- path where the results will be outputted
        kwargs (dict(str: any)) -- dictionary of keyword arguments. accepted arguments are:
            correction ('fdr', 'bonferroni') -- p-value correction method to use. defaults to fdr
    '''
    correction = 'fdr'
    if 'correction' in kwargs.keys():
        correction = kwargs['correction']
    
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
    df["chi2_score"] = [result[0]['score'] for result in results]
    df["p_val"] = [result[0]['p_val'] for result in results]
    if correction == 'fdr':
        df['adjusted_p_val'] = fdrcorrection(df['p_val'], alpha = 0.05, method= "indep")[1]
    df['frequency'] = [result[2] for result in results]
    df.to_csv(out_name)

def infogain(data, target, out_name, kwargs):
    '''
    DO NOT CALL DIRECTLY
    Runs infogain feature selection on the data and the target values. Outputs
    results to a .csv at given path

    Arguments:
        data (DataFrame) -- dataset
        target (str) -- target column label in dataset
        outname (str) -- path where the results will be outputted      
        kwargs (dict(str: any)) -- dictionary of keyword arguments. currently no use
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
    df["infogain_score"] = [result[0]['score'] for result in results]
    df['frequency'] = [result[2] for result in results]
    df.to_csv(out_name)

def mann_whitney_u(data, target, out_name, kwargs):
    '''
    DO NOT CALL DIRECTLY
    Runs mann-whitney-u feature selection on the data and the target values. Outputs
    results to a .csv at given path

    Arguments:
        data (DataFrame) -- dataset
        target (str) -- target column label in dataset
        outname (str) -- path where the results will be outputted
        kwargs (dict(str: any)) -- dictionary of keyword arguments. accepted arguments are:
            correction ('fdr', 'bonferroni') -- p-value correction method to use. defaults to fdr
    '''
    correction = 'fdr'
    if 'correction' in kwargs.keys():
        correction = kwargs['correction']
        
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
    df["mwu_1"] = [result[0]['score_1'] for result in results]
    df["mwu_2"] = [result[0]['score_2'] for result in results]
    df["mwu_score"] = [min(result[0]['score_1'], result[0]['score_2']) for result in results]
    df["p_val"] = [result[0]['p_val'] for result in results]
    if correction == 'fdr':
        df['adjusted_p_val'] = fdr_correction(df['p_val'], alpha = 0.05, method= "indep")[1]
    df['frequency'] = [result[2] for result in results]
    df.to_csv(out_name)

def ttest(data, target, out_name, kwargs):
    '''
    DO NOT CALL DIRECTLY
    Runs t_test feature selection on the data and the target values. Outputs
    results to a .csv at given path

    Arguments:
        data (DataFrame) -- dataset
        target (str) -- target column label in dataset
        outname (str) -- path where the results will be outputted
        kwargs (dict(str: any)) -- dictionary of keyword arguments. accepted arguments are:
            correction ('fdr', 'bonferroni') -- p-value correction method to use. defaults to fdr
    '''
    correction = 'fdr'
    if 'correction' in kwargs.keys():
        correction = kwargs['correction']
        
    start_time = time.time()
    logging.info('PARENT --- Started rounds of feature selection at: ' + time.ctime())
    target_arr = data[target].to_numpy().astype('int')
    only_snp_data = data.drop(columns = [target, 'ID_1'])

    shared_snp_data = SharedPandasDataFrame(only_snp_data)
    shared_target_arr = SharedNumpyArray(target_arr)
    
    individual_args = [(snp, shared_snp_data, shared_target_arr, 'ttest') for snp in only_snp_data]

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
    df['t_statistic'] = [result[0]['score'] for result in results]
    df['ttest_score'] = [abs(result[0]['score']) for result in results]
    df["p_val"] = [result[0]['p_val'] for result in results]
    if correction == 'fdr':
        df['adjusted_p_val'] = fdrcorrection(df['p_val'], alpha = 0.05, method= "indep")[1]
    df['frequency'] = [result[2] for result in results]
    df.to_csv(out_name)

def mrmr(data, target, out_name, kwargs):
    '''
    DO NOT CALL DIRECTLY
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
        n_selected_features = kwargs['n_selected_features']
        F, J_CMI, MIfy= LCSI.lcsi(data_arr, target_arr, gamma=0, function_name='MRMR', n_selected_features=n_selected_features)
    else:
        F, J_CMI, MIfy = LCSI.lcsi(data_arr, target_arr, gamma=0, function_name='MRMR')

    logging.info('MRMR --- Chosen indices are: {}'.format(F))
    logging.info('MRMR --- Therefore, chosen SNPs are: '.format(only_snp_data.columns[F]))
    df = pd.DataFrame()
    df['SNP'] = only_snp_data.columns.tolist()
    df['mrmr_score'] = 0
    df.reset_index(drop = True, inplace = True)
    df.loc[F, 'mrmr_score'] = 1
    df.to_csv(out_name)
    
def jmi(data, target, out_name, kwargs):
    '''
    DO NOT CALL DIRECTLY
    Applies MRMR feature selection on the data and target values. Outputs
    results to a .csv at given path

    Arguments:
        data (DataFrame) -- dataset
        target (str) -- target column label in dataset
        outname (str) -- path where the results will be outputted
        kwargs (
    ---------
    Brown, Gavin et al. "Conditional Likelihood Maximisation: A Unifying Framework for Information Theoretic Feature Selection." JMLR 2012.
    '''

    target_arr = data[target].to_numpy().astype('int')
    only_snp_data = data.drop(columns = [target, 'ID_1'])
    data_arr = only_snp_data.to_numpy()
    
    if 'n_selected_features' in kwargs.keys():
        n_selected_features = kwargs['n_selected_features']
        F, J_CMI, MIfy = LCSI.lcsi(data_arr, target_arr, function_name='JMI', n_selected_features=n_selected_features)
    else:
        F, J_CMI, MIfy = LCSI.lcsi(data_arr, target_arr, function_name='JMI')

    logging.info('JMI --- Chosen indices are: {}'.format(F))
    logging.info('JMI --- Therefore, chosen SNPs are: '.format(only_snp_data.columns[F]))
    df = pd.DataFrame()
    df['SNP'] = only_snp_data.columns.tolist()
    df['jmi_score'] = 0
    
    df.reset_index(drop = True, inplace = True)
    df.loc[F, 'jmi_score'] = 1
    df.to_csv(out_name)

def lasso(data, target, out_name, kwargs):
    '''
    DO NOT CALL DIRECTLY
    Applies LASSO feature selection on the data and target values. Outputs
    results to a .csv at given path

    Arguments:
        data (DataFrame) -- dataset
        target (str) -- target column label in dataset
        outname (str) -- path where the results will be outputted

        don't change alpha unless you really know what you are doing
    '''
    target_arr = data[target].to_numpy().astype('int')
    only_snp_data = data.drop(columns = [target, 'ID_1'])
    data_arr = only_snp_data.to_numpy()

    if 'outcome' not in kwargs.keys():
        raise Exception('Keyword argument \'outcome\' must be specified for Lasso feature selection')

    if kwargs['outcome'] not in ['continuous', 'discrete']:
        raise Exception('Keyword argument \'outcome\' must be \'continuous\' or \'discrete\'')

    n_selected_features = 50
    if 'n_selected_features' in kwargs.keys():
        n_selected_features = kwargs['n_selected_features']

    tolerance = 0.1
    if 'tolerance' in kwargs.keys():
        tolerance = kwargs['tolerance']
        
    n_upper = n_selected_features + n_selected_features * tolerance
    n_lower = n_selected_features - n_selected_features * tolerance

    if kwargs['outcome'] == 'discrete':
        '''
        Alpha optimization for discrete lasso assumes that the final alpha value will end up between 1 and positive infinity.
        Check feature_selector.log to see the progress. If the selector is picking too few with alpha <= 1, this will go in an 
        infinite loop.
        '''
        alpha = 1
        alpha_change = 0.5
        
        first_ascent = True
    
        selected_len = -1
    
        while selected_len < n_lower or selected_len > n_upper:
            logging.info('Running LASSO with alpha value: {}'.format(str(alpha)))
           
            lasso = LogisticRegression(penalty = 'l1', C = 1 / alpha, solver = 'liblinear', random_state = 42)
            lasso.fit(data_arr, target_arr)
                
            important_features = only_snp_data.columns[np.absolute(lasso.coef_[0]) > 0]
            selected_len = len(important_features)
            logging.info('Selected {} features.'.format(str(selected_len)))
    
            if selected_len > n_upper:
                if first_ascent:
                    alpha_change = alpha_change * 2
                    alpha += alpha_change
                else:
                    alpha_change = alpha_change / 2
                    alpha += alpha_change
            elif selected_len < n_lower:
                first_ascent = False
                alpha_change = alpha_change / 2
                alpha -= alpha_change

        df = pd.DataFrame()
        df['SNP'] = only_snp_data.columns.tolist()
        df['lasso_coeff'] = lasso.coef_[0]
        df['lasso_score'] = np.absolute(lasso.coef_[0])
        df.reset_index(drop = True, inplace = True)
        df.to_csv(out_name)

    elif kwargs['outcome'] == 'continuous':
        alpha = 1
        alpha_change = 0.5

        selected_len = -1

        while selected_len < n_lower or selected_len > n_upper:
            logging.info('Running LASSO with alpha value: {}'.format(str(alpha)))
           
            lasso = Lasso(alpha = alpha)  
            lasso.fit(data_arr, target_arr)

            important_features = only_snp_data.columns[np.absolute(lasso.coef_) > 0]
            selected_len = len(important_features)
            logging.info('Selected {} features.'.format(str(selected_len)))
    
            if selected_len > n_upper:
                alpha += alpha_change
                alpha_change = alpha_change / 2
            elif selected_len < n_lower:
                alpha -= alpha_change
                alpha_change = alpha_change / 2

        df = pd.DataFrame()
        df['SNP'] = only_snp_data.columns.tolist()
        df['lasso_coeff'] = lasso.coef_
        df['lasso_score'] = np.absolute(lasso.coef_)
        df.reset_index(drop = True, inplace = True)
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

    def frequency_map(self, ignore):
        '''
        Count SNP frequency for self.data.

        Arguments:
            ignore (list(str)) -- column labels to ignore while counting frequencies. usually this should be ['ID_1', 'PHQ9_binary'] ('PHQ9' for cont. outcome)

        Returns:
            freq_map (dict(str: int)) -- map where SNP identifiers are keys and frequencies are values
        '''
        only_snp_data = self.data.drop(columns = ignore)
        freq_map = {col: only_snp_data[col].sum() for col in only_snp_data}
        return freq_map

    @staticmethod
    def frequency_mask(data, threshold, freq_map):
        '''
        Hide SNPs from dataframe that have less than the desired frequency.

        Arguments:
            threshold (int) -- if either the group with the snp or without the snp is smaller than this number, the snp will be ignored
            ignore (list(str)) -- column labels to ignore while counting frequencies. usually this should be ['ID_1', 'PHQ9_binary'] ('PHQ9' for cont. outcome)

        Returns:
            data (DataFrame) -- a view of self.data with infrequent SNPs removed
        '''
        total = len(data)
        cols_to_drop = [snp for snp in freq_map if freq_map[snp] < threshold or (total - freq_map[snp] < threshold)]
        return data.drop(columns = cols_to_drop)
        
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
        freq_threshold,
        n_bootstraps,
        n_samples,
        stratify_column,
        selector_names,
        selector_kwargs,
        out_name,
        k_best = None,
        bootstraps = None,
    ):
        '''
        Bootstraps the dataset, applies feature selection with specified functions.
        Compiles results across all and outputs them as a .csv file.

        Arguments:
            freq_threshold (int) -- if either the group with the snp or without the snp is smaller than this number, the snp will be ignored
            n_bootstraps (int) -- number of bootstraps. ignored if bootstraps is not None. 
            n_samples (int) -- number of samples in each bootstrap. ignored if bootstraps is not None. pass None for same size as original sample size
            stratify_column (str) -- column label to use for feature selection and stratifying the bootstrap.
            selector_names (list(str)) -- list of function names that will be used to name subdirectories.
            selector_kwargs (list(dict(str: any))) -- list of dictionaries for kwargs to pass into selector functions
            out_name (str) -- name of subdirectories and compiled results file that will be created
            k_best (int) -- the final score of a snp will be the sum of this many best scores across all tests
            bootstraps (list(list(int))) -- if not None, use this to create samples instead of creating new random samples
        ''' 
        if len(selector_names) != len(selector_kwargs):
            raise Exception('Selector list must be as long as selector kwargs list')

        if bootstraps is not None:
            n_bootstraps = len(bootstraps)

        if k_best is None:
            k_best = n_bootstraps - 1

        if k_best > n_bootstraps:
            raise Exception('Cannot pick {} best scores out of {} bootstraps'.format(k_best, n_bootstraps))

        filenames = []
        bootstrap_export = []
        logging.info('PARENT --- Parent process is using {} MB of memory.'.format(psutil.Process(os.getpid()).memory_info().rss / 1024 ** 2))

        freq_map = self.frequency_map(['ID_1', stratify_column])

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
            this_sample = self.frequency_mask(this_sample, freq_threshold, freq_map)
            for j in range(len(selector_names)):
                selector_name = selector_names[j]
                selector_folder = os.path.join(self.out_folder, out_name + '_' + selector_name)
                if not os.path.exists(selector_folder):
                    os.makedirs(selector_folder)
                    logging.info('made a folder ' + selector_folder)
                filename = os.path.join(selector_folder, selector_names[j] + '_' + str(i) + '.csv')
                logging.info('PARENT --- Started {} at {}'.format(selector_name, time.ctime()))
                start = time.time()
                
                if selector_name == 'chi2':
                    chisquare(this_sample, stratify_column, filename, selector_kwargs[j])
                elif selector_name == 'infogain':
                    infogain(this_sample, stratify_column, filename, selector_kwargs[j])
                elif selector_name == 'mwu':
                    mann_whitney_u(this_sample, stratify_column, filename, selector_kwargs[j])
                elif selector_name == 'ttest':
                    ttest(this_sample, stratify_column, filename, selector_kwargs[j])
                elif selector_name == 'mrmr':
                    mrmr(this_sample, stratify_column, filename, selector_kwargs[j])
                elif selector_name == 'jmi':
                    jmi(this_sample, stratify_column, filename, selector_kwargs[j])
                elif selector_name == 'lasso':
                    lasso(this_sample, stratify_column, filename, selector_kwargs[j])
                else:
                    raise Exception('Unrecognized classifier name: {}'.format(selector_name))
                    
                logging.info('PARENT --- Finished {} at {}. That took {}'.format(selector_name, time.ctime(), str(time.time() - start)))
                filenames.append(filename)

        final = pd.DataFrame()
        snp_df_masked = self.frequency_mask(self.data.drop(columns = [stratify_column, 'ID_1']), freq_threshold, freq_map)
        snps = snp_df_masked.columns.tolist()
        final['SNP'] = snps
        final['frequency'] = np.zeros(len(snps))

        total_format = 'total_{}_' + str(k_best) + '_best'
        nan_format = 'nan_{}'
        target_format = '{}_score'
        
        for name in selector_names:
            final[total_format.format(name)] = np.zeros(len(snps))
            final[nan_format.format(name)] = np.zeros(len(snps))
            
        for file in filenames:
            curr_file = pd.read_csv(file)
            test_and_number = os.path.basename(file).split('.')[0]
            test_name = test_and_number.split('_')[0]
            if curr_file['SNP'].tolist() != snps:
                raise Exception('SNPs are not in order in {}'.format(file))
            target_column = target_format.format(test_name)
            final[test_and_number + '_score'] = curr_file[target_column]
            if 'p_val' in curr_file.columns:
                final[test_and_number + '_p_val'] = curr_file['p_val']
            if 'adjusted_p_val' in curr_file.columns:
                final[test_and_number + '_adjusted_p_val'] = curr_file['adjusted_p_val']

        column_format = '{}_{}_score'
        for snp in final['SNP']:
            for name in selector_names:
                results = []
                for j in range(n_bootstraps):
                    this_col = column_format.format(name, j)
                    value_cell = final.loc[final['SNP'] == snp, this_col]
                    if value_cell.isna().item():
                        final.loc[final['SNP'] == snp, nan_format.format(name)] += 1
                    else:
                        results.append(value_cell.item())
                if name == 'mwu':
                    results.sort()
                else:
                    results.sort(reverse = True)
                final.loc[final['SNP'] == snp, total_format.format(name)] = sum(results[:k_best])
            final.loc[final['SNP'] == snp, 'frequency'] = freq_map[snp]

        final.to_csv(os.path.join(self.out_folder, out_name + '.csv'))
            
        bootstrap_df = pd.DataFrame()
        for i in range(len(bootstrap_export)):
            name = 'bootstrap_' + str(i + 1)
            bootstrap_df[name] = bootstrap_export[i]

        bootstrap_df.to_csv(os.path.join(self.out_folder, out_name + '_bootstraps.csv'))
            

'''
Below is an example usage
'''


# def main():
#     data = pd.read_csv('/home/mminbay/summer_research/summer23_aylab/data/imputed_data/final_data/final_depression_allsnps_6000extra_c1.csv', index_col = 0)

#     data.drop(columns = ['Sex'], inplace = True)
    
#     fselect = FeatureSelector(
#         data, 
#         '/home/mminbay/summer_research/summer23_aylab/data/feat_select/'
#     )
#     fselect.bootstrapped_feat_select(
#         5,
#         3,
#         None,
#         'PHQ9_binary',
#         ['jmi']
#         [{'n_selected_features': 50}],
#         'jmi_test',
#         k_best = 2,
#         bootstraps = fselect.load_bootstraps('/home/mminbay/summer_research/summer23_aylab/example_bootstraps.csv')
    
# if __name__ == '__main__':
#     main()

            
        
        
    
    