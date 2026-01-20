function generate_report_xblockcompletion(input){
  var success_div = document.getElementById('xblockcompletion-success-msg');
  var error_div = document.getElementById('xblockcompletion-error-msg');
  var warning_div = document.getElementById('xblockcompletion-warning-msg');
  var url = input.dataset.endpoint;
  var errorMessage = gettext('Error generating problem report. Please refresh the page and try again.');
  return $.ajax({
      type: 'GET',
      dataType: 'json',
      url: url,
      error: function(error) {
          if (error.responseText) {
              errorMessage = JSON.parse(error.responseText);
          }
          error_div.textContent = errorMessage;
          error_div.style.display = 'block';
          success_div.style.display = 'none';
          warning_div.style.display = 'none';
          return true
      },
      success: function(data) {
          if (data.error) {
              error_div.textContent = errorMessage;
              error_div.style.display = 'block';
              success_div.style.display = 'none';
              warning_div.style.display = 'none';
          }
          else{
              if (data.error_task) {
                  warning_div.textContent = gettext('The report is already being generated, please wait.');
                  warning_div.style.display = 'block';
                  error_div.style.display = 'none';
                  success_div.style.display = 'none';
              }
              else{
                  success_div.textContent = data.status;
                  success_div.style.display = 'block';
                  warning_div.style.display = 'none';
                  error_div.style.display = 'none';
              }
          }
          return true
      }
  });
}
