# My site source code

Based on [Beautiful Jekyll](https://beautifuljekyll.com/)

## How to run locally

- Install Ruby and Jekyll

    ```bash
    sudo apt-get install ruby-full build-essential zlib1g-dev
    echo '# Install Ruby Gems to ~/gems' >> ~/.bashrc
    echo 'export GEM_HOME="$HOME/gems"' >> ~/.bashrc
    echo 'export PATH="$HOME/gems/bin:$PATH"' >> ~/.bashrc
    source ~/.bashrc
    ```

- Clone the repository

    ```bash
    git clone
    cd
    ```

- Install dependencies

    ```bash
    bundle install
    ```

- Run the server

    ```bash
    bundle exec jekyll serve
    ```

The page will be available at `http://localhost:4000/`

## Tips for posts

### Boxes

You can add notification, warning and error boxes like this:

#### Notification

{: .box-note}
**Note:** This is a notification box.

#### Warning

{: .box-warning}
**Warning:** This is a warning box.

#### Error

{: .box-error}
**Error:** This is an error box.

#### Success

{: .box-success}
**Success:** This is a success box.
