from django.db import migrations
from django.db import connection

def check_mariadb(apps, schema_editor):
    if connection.vendor == 'mysql':
        # Check if it's specifically MariaDB
        with connection.cursor() as cursor:
            cursor.execute("SELECT VERSION()")
            version = cursor.fetchone()[0].lower()
            if 'mariadb' in version:
                # Execute partitioning SQL
                cursor.execute('''
                    ALTER TABLE deces_deces
                    PARTITION BY RANGE (YEAR(date_deces)) (

                    -- Partition definitions
                        PARTITION p1970 VALUES LESS THAN (1971),
                        PARTITION p1971 VALUES LESS THAN (1972),
                        PARTITION p1972 VALUES LESS THAN (1973),
                        PARTITION p1973 VALUES LESS THAN (1974),
                        PARTITION p1974 VALUES LESS THAN (1975),
                        PARTITION p1975 VALUES LESS THAN (1976),
                        PARTITION p1976 VALUES LESS THAN (1977),
                        PARTITION p1977 VALUES LESS THAN (1978),
                        PARTITION p1978 VALUES LESS THAN (1979),
                        PARTITION p1979 VALUES LESS THAN (1980),
                        PARTITION p1980 VALUES LESS THAN (1981),
                        PARTITION p1981 VALUES LESS THAN (1982),
                        PARTITION p1982 VALUES LESS THAN (1983),
                        PARTITION p1983 VALUES LESS THAN (1984),
                        PARTITION p1984 VALUES LESS THAN (1985),
                        PARTITION p1985 VALUES LESS THAN (1986),
                        PARTITION p1986 VALUES LESS THAN (1987),
                        PARTITION p1987 VALUES LESS THAN (1988),
                        PARTITION p1988 VALUES LESS THAN (1989),
                        PARTITION p1989 VALUES LESS THAN (1990),
                        PARTITION p1990 VALUES LESS THAN (1991),
                        PARTITION p1991 VALUES LESS THAN (1992),
                        PARTITION p1992 VALUES LESS THAN (1993),
                        PARTITION p1993 VALUES LESS THAN (1994),
                        PARTITION p1994 VALUES LESS THAN (1995),
                        PARTITION p1995 VALUES LESS THAN (1996),
                        PARTITION p1996 VALUES LESS THAN (1997),
                        PARTITION p1997 VALUES LESS THAN (1998),
                        PARTITION p1998 VALUES LESS THAN (1999),
                        PARTITION p1999 VALUES LESS THAN (2000),
                        PARTITION p2000 VALUES LESS THAN (2001),
                        PARTITION p2001 VALUES LESS THAN (2002),
                        PARTITION p2002 VALUES LESS THAN (2003),
                        PARTITION p2003 VALUES LESS THAN (2004),
                        PARTITION p2004 VALUES LESS THAN (2005),
                        PARTITION p2005 VALUES LESS THAN (2006),
                        PARTITION p2006 VALUES LESS THAN (2007),
                        PARTITION p2007 VALUES LESS THAN (2008),
                        PARTITION p2008 VALUES LESS THAN (2009),
                        PARTITION p2009 VALUES LESS THAN (2010),
                        PARTITION p2010 VALUES LESS THAN (2011),
                        PARTITION p2011 VALUES LESS THAN (2012),
                        PARTITION p2012 VALUES LESS THAN (2013),
                        PARTITION p2013 VALUES LESS THAN (2014),
                        PARTITION p2014 VALUES LESS THAN (2015),
                        PARTITION p2015 VALUES LESS THAN (2016),
                        PARTITION p2016 VALUES LESS THAN (2017),
                        PARTITION p2017 VALUES LESS THAN (2018),
                        PARTITION p2018 VALUES LESS THAN (2019),
                        PARTITION p2019 VALUES LESS THAN (2020),
                        PARTITION p2020 VALUES LESS THAN (2021),
                        PARTITION p2021 VALUES LESS THAN (2022),
                        PARTITION p2022 VALUES LESS THAN (2023),
                        PARTITION p2023 VALUES LESS THAN (2024),
                        PARTITION p2024 VALUES LESS THAN (2025),
                        PARTITION p_future VALUES LESS THAN MAXVALUE
                    )
                ''')

def reverse_mariadb(apps, schema_editor):
    if connection.vendor == 'mysql':
        with connection.cursor() as cursor:
            cursor.execute("SELECT VERSION()")
            version = cursor.fetchone()[0].lower()
            if 'mariadb' in version:
                # Remove partitioning
                cursor.execute('ALTER TABLE deces_deces REMOVE PARTITIONING')

class Migration(migrations.Migration):
    dependencies = [
        ('deces', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(
            code=check_mariadb,
            reverse_code=reverse_mariadb
        )
    ]
