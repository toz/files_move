# -*- coding: utf-8 -*-
#########################################################
# python
import os
import sys
import datetime
import traceback
import threading
import re
import subprocess
import shutil
import time
import urllib
import rclone
import daum_tv

# third-party
from sqlalchemy import desc
from sqlalchemy import or_, and_, func, not_
from guessit import guessit

# sjva 공용
from framework import app, db, scheduler, path_app_root, celery
from framework.job import Job
from framework.util import Util
from system.model import ModelSetting as SystemModelSetting

# 패키지
from .plugin import logger, package_name
from .model import ModelSetting, ModelMediaItem


#########################################################
class LogicNormal(object):

    @staticmethod
    @celery.task
    def scheduler_function():
        try:
            logger.debug("파일정리 시작!")
            source_base_path = ModelSetting.get_setting_value('source_base_path')
            ktv_base_path = ModelSetting.get_setting_value('ktv_base_path')
            movie_base_path = ModelSetting.get_setting_value('movie_base_path')
            error_path = ModelSetting.get_setting_value('error_path')
            interval = ModelSetting.get('interval')
            emptyFolderDelete = ModelSetting.get('emptyFolderDelete')

            source_base_path = [ x.strip() for x in source_base_path.split(',') ]
            if not source_base_path:
                return None
            if None == '':
                return None

            try:
                sub_folders, files = LogicNormal.run_fast_scandir(source_base_path, [".*"])
                for path in sub_folders:
                    fileList = LogicNormal.make_list(path, files, ktv_base_path, movie_base_path, error_path)
                #time.sleep(int(interval))

                if ModelSetting.get_bool('emptyFolderDelete'):
                    sub_folders.reverse()
                    for dir_path in sub_folders:
                        logger.debug( "dir_path : " + dir_path)
                        if source_path != dir_path and len(os.listdir(dir_path)) == 0:
                            os.rmdir(unicode(dir_path))

            except Exception as e:
                logger.error('Exception:%s', e)
                logger.error(traceback.format_exc())

        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def run_fast_scandir(dir, ext):    # dir: str, ext: list
        subfolders, files = [], []

        for f in os.scandir(dir):
            if f.is_dir():
                subfolders.append(f.path)
            if f.is_file():
                if os.path.splitext(f.name)[1].lower() in ext:
                    files.append(f.path)

        for dir in list(subfolders):
            sf, f = run_fast_scandir(dir, ext)
            subfolders.extend(sf)
            files.extend(f)

        logger.debug('sf:%s, files:%s', subfolders, files)
        return subfolders, files

    @staticmethod
    def make_list(source_path, files, ktv_path, movie_path, err_path):
        try:
            item = {}
            item['path'] = source_path
            item['name'] = files
            item['fullPath'] = os.path.join(source_path, files)
            item['guessit'] = guessit(files)
            item['ext'] = os.path.splitext(files)[1].lower()
            item['search_name'] = None
            match = re.compile('^(?P<name>.*?)[\\s\\.\\[\\_\\(]\\d{4}').match(item['name'])
            logger.debug('ml - match: %s', match)
            if match:
                item['search_name'] = match.group('name').replace('.', ' ').strip()
                logger.debug('ml 1 - item[search_name]: %s', item['search_name'])
                item['search_name'] = re.sub('\\[(.*?)\\]', '', item['search_name'])
                logger.debug('ml 2 - item[search_name]: %s', item['search_name'])
            #else:
                #item['search_name'] = item['title']
                #logger.debug('ml - search_name: %s', item['search_name'])
            if LogicNormal.isHangul(item['name']) > 0:
                item['search_name'] = files

            LogicNormal.check_move_list(item, ktv_path, movie_path, err_path)

        except Exception as e:
            logger.error('Exxception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def check_move_list(item, ktv_target_path, movie_target_path, error_target_path):
        try:
            if 'episode' in item['guessit']:
                #TV
                logger.debug('cml - drama ' + item['name'])
                daum_tv_info = daum_tv.Logic.get_daum_tv_info(item['name'])
                if daum_tv_info:
                    logger.debug('cml - daum_tv_info[countries]: %s', daum_tv_info['countries'])
                    for country in daum_tv_info['countries']:
                        item['country'] = daum_tv_info.countries.add(country.strip())

                    logger.debug('cml - item[country]: %s', item['country'])
                    if 'country' in item['country'] == u'한국':
                        logger.debug('cml - drama condition ok ' + item['name'])
                        LogicNormal.move_ktv(item, daum_tv_info, ktv_target_path)
                    else:
                        logger.debug('cml - drama condition not ok ' + item['name'])
                        LogicNormal.move_except(item, error_target_path)
                else:
                    logger.debug('cml - drama condition not not ok ' + item['name'])
                    LogicNormal.move_except(item, error_target_path)

            else:
                #Movie
                logger.debug('cml - movie ' + item['name'])
                if LogicNormal.isHangul(item['name']) is False:
                    if 'year' in item['guessit']:
                        year = item['guessit']['year']
                        logger.debug('cml - movie year ' + year)
                        (item['is_include_kor'], daum_movie_info) = daum_tv.MovieSearch.search_movie(item['search_name'], item['guessit']['year'])
                        logger.debug('cml - movie ' + item['name'] + item['search_name'])
                        if daum_movie_info and daum_movie_info[0]['score'] == 100:
                            #item['movie'] = movie[0]
                            logger.debug('cml - movie condition ok ' + item['name'])
                            LogicNormal.set_movie(item, daum_movie_info[0])
                            LogicNormal.move_movie(item, daum_movie_info[0], movie_target_path)
                        else:
                            logger.debug('cml - movie condition not ok ' + item['name'])
                            LogicNormal.move_except(item, error_target_path)
                    else:
                        logger.debug('cml - movie condition not not ok ' + item['name'])
                        LogicNormal.move_except(item, error_target_path)
                else:
                    logger.debug('cml - movie is hangul ' + item['name'])
                    (item['is_include_kor'], daum_movie_info) = daum_tv.MovieSearch.search_movie(item['search_name'], 2020)
                    logger.debug('cml - movie ' + item['name'] + item['search_name'])
                    if daum_movie_info and daum_movie_info[0]['score'] == 100:
                        LogicNormal.set_movie(item, daum_movie_info[0])
                        LogicNormal.move_movie(item, daum_movie_info[0], movie_target_path)

        except Exception as e:
            logger.error('Exxception:%s', e)
            logger.error(traceback.format_exc())


    @staticmethod
    def set_movie(data, movie):
        try:
            data['movie'] = movie
            data['dest_folder_name'] = '%s' % (re.sub('[\\/:*?"<>|]', '', movie['title']).replace('  ', ' '))
            if 'more' in movie:
                Logic = Logic
                import logic
                folder_rule = Logic.get_setting_value('folder_rule')
                tmp = folder_rule.replace('%TITLE%', movie['title']).replace('%YEAR%', movie['year']).replace('%ENG_TITLE%', movie['more']['eng_title']).replace('%COUNTRY%', movie['more']['country']).replace('%GENRE%', movie['more']['genre']).replace('%DATE%', movie['more']['date']).replace('%RATE%', movie['more']['rate']).replace('%DURING%', movie['more']['during'])
                tmp = re.sub('[\\/:*?"<>|]', '', tmp).replace('  ', ' ').replace('[]', '')
                data['dest_folder_name'] = tmp
        except Exception as e:
            logger.error('Exxception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def move_ktv(data, info, base_path):
        try:
            logger.debug('=== title %s', info.title)
            dest_folder_path = os.path.join(base_path, u'드라마', u'한국',info.title)
            if not os.path.isdir(dest_folder_path):
                os.makedirs(dest_folder_path)
            shutil.move(data['fullPath'], dest_folder_path)
            LogicNormal.db_save(data, dest_folder_path)

        except Exception as e:
            logger.error('Exxception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def move_except(data, base_path):
        try:
            dest_folder_path = os.path.join(base_path)
            logger.debug('me - move exception %s' , data['search_name'])
            #if not os.path.isdir(dest_folder_path):
            #    os.makedirs(dest_folder_path)
            #shutil.move(data['fullPath'], dest_folder_path)
            #LogicNormal.db_save(data, dest_folder_path)

        except Exception as e:
            logger.error('Exxception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def move_movie(data, info, base_path):
        try:
            logger.debug('mm - info[more][country]: %s', info['more']['country'])
            if info['more']['country'] == u'한국':
                set_country = u'한국'
            elif info['more']['country'] == u'중국':
                set_country = u'증국'
            elif info['more']['country'] == u'홍콩':
                set_country = u'증국'
            elif info['more']['country'] == u'대만':
                set_country = u'증국'
            elif info['more']['country'] == u'일본':
                set_country = u'일본'
            else:
                set_country = u'외국'

            if info['year'] < 1990:
                set_year = u'1900s'
            elif info['year'] >= 1990 and info['year'] < 2000:
                set_year = u'1990s'
            elif info['year'] >= 2000 and info['year'] < 2010:
                set_year = u'2000s'
            elif info['year'] >= 2010 and info['year'] <= 2012:
                set_year = u'~2012'
            elif info['year'] == 2013:
                set_year = u'2013'
            elif info['year'] == 2014:
                set_year = u'2014'
            elif info['year'] == 2015:
                set_year = u'2015'
            elif info['year'] == 2016:
                set_year = u'2016'
            elif info['year'] == 2017:
                set_year = u'2017'
            elif info['year'] == 2018:
                set_year = u'2018'
            elif info['year'] == 2019:
                set_year = u'2019'
            elif info['year'] == 2020:
                set_year = u'2020'

            dest_folder_path = os.path.join(base_path, u'영화', set_country, set_year, data['dest_folder_name'])
            if not os.path.isdir(dest_folder_path):
                os.makedirs(dest_folder_path)
            shutil.move(data['fullPath'], dest_folder_path)
            LogicNormal.db_save(data, dest_folder_path)

        except Exception as e:
            logger.error('Exxception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def db_save(data, dest):
        try:
            entity = {}
            entity['name'] = data['search_name']
            entity['fileName'] = data['name']
            entity['dirName'] = data['fullPath']
            entity['targetPath'] = dest
            ModelMediaItem.save_as_dict(entity)

        except Exception as e:
            logger.error('Exxception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def isHangul(text):

        if type(text) is not unicode:
            encText = text.decode('utf-8')
        else:
            encText = text

        hanCount = len(re.findall(u'[\u3130-\u318F\uAC00-\uD7A3]+', encText))

        return hanCount > 0

