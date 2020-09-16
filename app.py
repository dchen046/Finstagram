from flask import Flask, render_template, request, session, redirect, url_for, send_file
import os
import uuid
import hashlib
import pymysql.cursors
from functools import wraps
import time

app = Flask(__name__)
app.secret_key = "super secret key"
IMAGES_DIR = os.path.join(os.getcwd(), "images")

connection = pymysql.connect(host="localhost",
                             user="root",
                             password="root",
                             db="finsta",
                             charset="utf8mb4",
                             port=8889,
                             cursorclass=pymysql.cursors.DictCursor,
                             autocommit=True)

def login_required(f):
    @wraps(f)
    def dec(*args, **kwargs):
        if not "username" in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return dec


@app.route("/")
def index():
    if "username" in session:
        return redirect(url_for("home"))
    return render_template("index.html")


@app.route("/home")
@login_required
def home():
    return render_template("home.html", username=session["username"])


@app.route("/upload", methods=["GET"])
@login_required
def upload():
    return render_template("upload.html")


@app.route("/images", methods=["GET"])
@login_required
def images():
    username = session["username"]
    # query for photos visible by current user (can view own photos too)
    query = "SELECT filepath, firstName, lastName, p.photoID, postingdate, caption " \
            "FROM photo AS p JOIN person ON username = photoPoster " \
            "WHERE photoPoster = %s " \
            "OR (p.photoPoster IN " \
            "(SELECT username_followed FROM follow " \
            "WHERE username_follower = %s AND followstatus = TRUE) AND p.allFollowers = TRUE) " \
            "OR p.photoID IN" \
            "(SELECT photoID FROM photo NATURAL JOIN (sharedWith NATURAL JOIN BelongTo)" \
            "WHERE groupOwner = %s OR member_username = %s) " \
            "ORDER BY postingdate DESC"
    with connection.cursor() as cursor:
        cursor.execute(query, (username, username, username, username))
    visiblePhotos = cursor.fetchall()

    # query for photos with tags
    query = "SELECT p.photoID, t.username, pr.firstName, pr.lastName " \
            "FROM photo AS p JOIN (Tagged AS t NATURAL JOIN person AS pr) ON p.photoID = t.photoID " \
            "WHERE t.tagstatus = TRUE"
    with connection.cursor() as cursor:
        cursor.execute(query)
    tags = cursor.fetchall()

    # query to get the likes of each photo
    query = "SELECT * FROM photo AS p JOIN likes as l ON p.photoID = l.photoID"
    with connection.cursor() as cursor:
        cursor.execute(query)
    likes = cursor.fetchall()

    return render_template("images.html", images=visiblePhotos, tagged=tags, likes=likes)


@app.route("/image/<image_name>", methods=["GET"])
def image(image_name):
    image_location = os.path.join(IMAGES_DIR, image_name)
    if os.path.isfile(image_location):
        return send_file(image_location, mimetype="image/jpg")


@app.route("/login", methods=["GET"])
def login():
    return render_template("login.html")


@app.route("/register", methods=["GET"])
def register():
    return render_template("register.html")


@app.route("/loginAuth", methods=["POST"])
def loginAuth():
    if request.form:
        requestData = request.form
        username = requestData["username"]
        # password with added salt
        password = requestData["password"] + "cs3083"
        hashedPass = hashlib.sha256(password.encode("utf-8")).hexdigest()

        #checking if hashed password is the same as stored
        with connection.cursor() as cursor:
            query = "SELECT * FROM person WHERE username = %s AND password = %s"
            cursor.execute(query, (username, hashedPass))
        data = cursor.fetchone()
        if data:
            session["username"] = username
            return redirect(url_for("home"))

        error = "Incorrect username or password."
        return render_template("login.html", error=error)

    error = "An unknown error has occurred. Please try again."
    return render_template("login.html", error=error)


@app.route("/registerAuth", methods=["POST"])
def registerAuth():
    username = request.form['username']
    # password with added salt
    password = request.form['password'] + "cs3083"
    hashedPass = hashlib.sha256(password.encode("utf-8")).hexdigest();
    firstName = request.form["fname"]
    lastName = request.form["lname"]

    #cursor used to send queries
    cursor = connection.cursor()
    #executes query
    query = 'SELECT * FROM person WHERE username = %s'
    cursor.execute(query, (username))
    #stores the results in a variable
    data = cursor.fetchone()
    #use fetchall() if you are expecting more than 1 data row
    error = None
    if(data):
        #If the previous query returns data, then user exists
        error = "This user already exists"
        return render_template('register.html', error = error)
    else:
        ins = 'INSERT INTO person(username, password, firstName, lastName) VALUES(%s, %s, %s, %s)'
        cursor.execute(ins, (username, hashedPass, firstName, lastName))
        connection.commit()
        cursor.close()
        return render_template('index.html')


@app.route("/logout", methods=["GET"])
def logout():
    session.pop("username")
    return redirect("/")


@app.route("/uploadImage", methods=["POST"])
@login_required
def upload_image():
    if request.files:
        image_file = request.files.get("imageToUpload", "")
        image_name = image_file.filename
        filepath = os.path.join(IMAGES_DIR, image_name)
        image_file.save(filepath)
        # gets the username of current session
        poster = session["username"]
        caption = request.form["caption"]
        allFollowers = request.form.get("allFollowers")
        timePosted = time.strftime('%Y-%m-%d %H:%M:%S')
        query = "INSERT INTO photo (postingDate, filepath, allFollowers, caption, photoPoster) VALUES (%s, %s, %s, %s, %s)"
        with connection.cursor() as cursor:
            if allFollowers:
                cursor.execute(query, (timePosted, image_name, True, caption, poster))
                connection.commit()
                cursor.close()
                message = "Image has been successfully uploaded."
                return render_template("upload.html", message=message)
            else:
                # allFollowers not checked
                cursor.execute(query, (timePosted, image_name, False, caption, poster))
                # get friend groups from text box parse with comma (,) for multiple groups
                connection.commit()
                # gettings friend groups owned by user
                query = "SELECT groupName FROM Friendgroup WHERE groupOwner = %s"
                cursor.execute(query, session["username"])
                friendGroups = cursor.fetchall()
                return render_template("selectFG.html", groups=friendGroups)
    else:
        message = "Failed to upload image."
        return render_template("upload.html", message=message)


@app.route("/selectFG", methods=["POST"])
@login_required
def selectFG():
    with connection.cursor() as cursor:
        # getting friend groups owned by user
        query = "SELECT groupName FROM Friendgroup WHERE groupOwner = %s"
        cursor.execute(query, session["username"])
        friendGroups = cursor.fetchall()

        # get the most recent photo added by user that has allFollowers = false
        query = "SELECT photoID FROM photo WHERE photoPoster = %s " \
                "ORDER BY postingdate DESC"
        cursor.execute(query, session["username"])
        photo = cursor.fetchone()
        # loop through all friend groups to see which one to share with
        for row in friendGroups:
            selectedGroup = request.form.get(row["groupName"])
            if selectedGroup:
                query = "INSERT INTO SharedWith (groupOwner, groupName, photoID)" \
                        "Values (%s,%s,%s)"
                cursor.execute(query, (session["username"], row["groupName"], photo["photoID"]))
                connection.commit()
    message = "Image has been successfully uploaded"
    return render_template("upload.html", message=message)


@app.route("/follow", methods=["GET"])
@login_required
def follow():
    return render_template("follow.html")


@app.route("/sendFollow", methods=["POST"])
@login_required
def sendFollow():
    # be able follow a valid user
    username = session["username"]
    followUsername = request.form["follow"]
    query = "SELECT username FROM person WHERE username = %s"
    with connection.cursor() as cursor:
        cursor.execute(query, followUsername)
    message = "Invalid username"
    # if its a valid user
    if cursor.rowcount > 0:
        # check if there is already a request
        query = "SELECT * FROM follow " \
                "WHERE username_followed = %s AND username_follower = %s"
        with connection.cursor() as cursor:
            cursor.execute(query, (followUsername, username))
        if cursor.rowcount == 0: # a request has not been sent
            query = "INSERT INTO follow (username_followed, username_follower, followstatus) " \
                    "VALUES (%s, %s, False)"
            with connection.cursor() as cursor:
                cursor.execute(query, (followUsername, username))
            connection.commit()
            cursor.close()
            message = "Follow Request Sent."
        elif cursor.fetchone()["followstatus"] == 1:
            message = "You already follow that user."
        else:
            message = "You already sent a request."
    return render_template("follow.html", message=message)


@app.route("/followReq", methods=["GET"])
@login_required
def followReq():
    username = session["username"]
    query = "SELECT username_follower FROM follow WHERE username_followed = %s AND followstatus = False"
    with connection.cursor() as cursor:
        cursor.execute(query, username)
    requests = cursor.fetchall()
    return render_template("followReq.html", requests=requests)


@app.route("/manage", methods=["POST"])
@login_required
def manage():
    # if checkbox is checked then follow them if not then delete the request
    username = session["username"]
    query = "SELECT username_follower FROM follow " \
            "WHERE username_followed = %s AND followstatus = False"
    with connection.cursor() as cursor:
        cursor.execute(query, username)
    fReqs = cursor.fetchall()

    for row in fReqs:
        follower = row["username_follower"]
        accepted = request.form.get(follower)
        if accepted:
            query = "UPDATE follow SET followstatus = True " \
                    "WHERE username_followed = %s and username_follower = %s"
            with connection.cursor() as cursor:
                cursor.execute(query, (username, follower))
            connection.commit()
            cursor.close()
        else:
            query = "DELETE FROM follow " \
                    "WHERE username_followed = %s AND username_follower = %s"
            with connection.cursor() as cursor:
                cursor.execute(query, (username, follower))
            connection.commit()
            cursor.close()
    message = "Requests Updated."
    return render_template("followReq.html", message=message)


@app.route("/searchBy", methods=["GET"])
@login_required
def searchByUser():
    return render_template("searchBy.html")


@app.route("/searchUserOrTag", methods=["POST"])
@login_required
def searchUserOrTag():
    username = session["username"]
    searchInput = request.form["search"]
    searchByTag = request.form.get("searchByTag")
    if searchByTag:
        query = "SELECT filepath, firstName, lastName, p.photoID, postingdate, caption " \
                "FROM (photo AS p JOIN person ON username = photoPoster) " \
                "JOIN Tagged as t on p.photoID = t.photoID " \
                "WHERE t.username = %s AND tagstatus = TRUE " \
                "AND (photoPoster = %s " \
                "OR (p.photoPoster IN " \
                "(SELECT username_followed FROM follow " \
                "WHERE username_follower = %s AND followstatus = TRUE) AND p.allFollowers = TRUE) " \
                "OR p.photoID IN" \
                "(SELECT photoID FROM photo NATURAL JOIN (sharedWith NATURAL JOIN BelongTo)" \
                "WHERE groupOwner = %s OR member_username = %s)) " \
                "ORDER BY postingdate DESC"
        with connection.cursor() as cursor:
            cursor.execute(query, (searchInput, username, username, username, username))
        visiblePhotos = cursor.fetchall()
    else:
        # query for visible photos by certain poster
        if username == searchInput:
            # this is only for whe you want to see current user images
            query = "SELECT filepath, firstName, lastName, p.photoID, postingdate, caption " \
                    "FROM photo AS p JOIN person ON username = photoPoster " \
                    "WHERE photoPoster = %s ORDER BY postingdate DESC"
            with connection.cursor() as cursor:
                cursor.execute(query, username)
        else:
            query = "SELECT filepath, firstName, lastName, p.photoID, postingdate, caption " \
                    "FROM photo AS p JOIN person ON username = photoPoster " \
                    "WHERE photoPoster = %s " \
                    "AND ((p.photoPoster IN " \
                    "(SELECT username_followed FROM follow " \
                    "WHERE username_follower = %s AND followstatus = TRUE) AND p.allFollowers = TRUE) " \
                    "OR p.photoID IN" \
                    "(SELECT photoID FROM photo NATURAL JOIN (sharedWith NATURAL JOIN BelongTo)" \
                    "WHERE groupOwner = %s OR member_username = %s)) " \
                    "ORDER BY postingdate DESC"
            with connection.cursor() as cursor:
                cursor.execute(query, (searchInput, username, username, username))
        visiblePhotos = cursor.fetchall()

    # query for photos with tags
    query = "SELECT p.photoID, t.username, pr.firstName, pr.lastName " \
            "FROM photo AS p JOIN (Tagged AS t NATURAL JOIN person AS pr) ON p.photoID = t.photoID " \
            "WHERE t.tagstatus = TRUE"
    with connection.cursor() as cursor:
        cursor.execute(query)
    tags = cursor.fetchall()

    # query to get the likes of each photo
    query = "SELECT * FROM photo AS p JOIN likes as l ON p.photoID = l.photoID"
    with connection.cursor() as cursor:
        cursor.execute(query)
    likes = cursor.fetchall()
    return render_template("searchBy.html", images=visiblePhotos, tagged=tags, likes=likes)


if __name__ == "__main__":
    if not os.path.isdir("images"):
        os.mkdir(IMAGES_DIR)
    app.run()
