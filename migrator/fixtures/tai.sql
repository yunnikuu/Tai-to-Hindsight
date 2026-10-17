CREATE TABLE AppModels (ID INTEGER PRIMARY KEY, Name TEXT, Alias TEXT, Description TEXT, File TEXT, CategoryID INTEGER DEFAULT 0, IconFile TEXT, TotalTime INTEGER DEFAULT 0);
CREATE TABLE HoursLogModels (ID INTEGER PRIMARY KEY, DataTime TEXT, Time INTEGER DEFAULT 0, AppModelID INTEGER);
CREATE TABLE DailyLogModels (ID INTEGER PRIMARY KEY, Date TEXT, Time INTEGER DEFAULT 0, AppModelID INTEGER);
CREATE TABLE CategoryModels (ID INTEGER PRIMARY KEY, Name TEXT, IconFile TEXT, Color TEXT, IsDirectoryMath INTEGER, Directories TEXT);
INSERT INTO CategoryModels(ID,Name,Color) VALUES (1,'开发','#A78BFA'),(2,'浏览','#60A5FA');
INSERT INTO AppModels(ID,Name,Alias,File,CategoryID) VALUES (1,'Code','Visual Studio Code','C:\Apps\Code.exe',1),(2,'chrome','谷歌浏览器','C:\Apps\chrome.exe',2);
